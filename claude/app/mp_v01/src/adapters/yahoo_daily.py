"""
Yahoo Finance daily-bar adapter (FREE).

Runs on Tyler's machine via Codex, not in Claude's sandbox (no external network there).

WHAT YAHOO GIVES YOU FREE:
  - Daily OHLCV equity bars, decades of history          <- sufficient for the ENTIRE stock layer
  - Dividends and splits (for total-return construction)
  - CURRENT option chains only

WHAT IT DOES NOT GIVE YOU:
  - Historical option chains. Verified: yfinance returns prices only for
    currently-listed, non-expired contracts. There is no way to ask "what did
    the SPY chain look like on 2024-03-05."

STRATEGIC CONSEQUENCE, and it is the reason this file exists:
The stock-thesis layer can be built and validated for $0. Options data is only
required AFTER a stock-level edge is demonstrated. If the forward excess-return
forecast has no edge, no options overlay can rescue it - you would be selecting
contracts on a coin flip. So: spend nothing until the free layer proves something.

FORWARD CAPTURE (start this now, it costs nothing):
Yahoo's CURRENT chain, snapshotted daily and stored immutably with an
available_time, accumulates into a genuinely point-in-time options history.
Six months of daily snapshots is six months of honest data you cannot buy
retroactively at any price, because vendors' historical files are reconstructions.

AVAILABILITY SEMANTICS - the part that matters for correctness:
A daily bar for date D is NOT available at 15:45 ET on D. It is final only after
the 16:00 close, and Yahoo publishes with a lag. Treating a bar as available on
its own date is the single easiest way to inject one full day of lookahead into
every prediction. bar_available_time() below encodes this conservatively.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from common.timezones import US_EASTERN as NY

# Conservative: a session's daily bar is treated as consumable the following
# morning, not at that session's own close. Tighten only with measured evidence
# of actual publication latency.
BAR_AVAILABILITY_LAG_HOURS = 17  # 16:00 ET close -> ~09:00 ET next morning


def bar_available_time(bar_date: str) -> datetime:
    """When a daily bar for `bar_date` could first legitimately be consumed."""
    y, m, d = (int(x) for x in bar_date.split("-"))
    close_et = datetime(y, m, d, 16, 0, tzinfo=NY)
    return (close_et + timedelta(hours=BAR_AVAILABILITY_LAG_HOURS)).astimezone(timezone.utc)


def bar_event_time(bar_date: str) -> datetime:
    """The close the bar describes."""
    y, m, d = (int(x) for x in bar_date.split("-"))
    return datetime(y, m, d, 16, 0, tzinfo=NY).astimezone(timezone.utc)


def daily_total_return(close_prev: float, close: float, dividend: float = 0.0) -> float:
    """Simple daily TOTAL return including distributions.

    Uses raw closes plus the cash distribution rather than vendor-adjusted
    closes. Adjusted-close series are silently rewritten whenever a vendor
    restates adjustment factors, which retroactively changes historical
    features - exactly the silent-revision class the project prohibits.

    SPLITS - a load-bearing assumption, stated here because it was previously
    only implied. There is no split term in this formula. It is correct only
    because Yahoo's `Close` under auto_adjust=False is nonetheless adjusted for
    splits (it is unadjusted for DIVIDENDS, which is the part we want, and which
    is why the dividend is added back explicitly above).

    Verified 2026-09-02 against NVDA's 10-for-1 split effective 2024-06-10,
    fetched live with yfinance 1.7.0: this function returned +0.7461% for that
    session, matching the ~0.75% reported independently. Had `Close` been
    genuinely unadjusted, the same session would have produced roughly -90%,
    and the label contract would have scored a fabricated crash as a real one.

    This is an assumption about a third-party scraper, not a guarantee. If a
    future Yahoo or yfinance change makes `Close` truly raw, every split in the
    history becomes a fake catastrophic move and NOTHING here will complain.
    Re-verify against a known split after any yfinance upgrade.
    """
    if close_prev <= 0:
        raise ValueError(f"Non-positive prior close {close_prev}")
    return (close + dividend) / close_prev - 1.0


def normalize_bars(raw_rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    """
    Convert raw provider rows into records carrying the four-timestamp contract.

    Expected raw row keys: date (YYYY-MM-DD), open, high, low, close, volume,
    and optionally dividend.

    Missing or unusable values are marked UNKNOWN. Nothing is interpolated,
    carried forward, or estimated - see the module docstring in the ingestion
    package. A gap is reported, never patched.
    """
    out: list[dict[str, Any]] = []
    prev_close: float | None = None
    for row in raw_rows:
        date = row.get("date")
        close = row.get("close")
        # `close != close` is true only for NaN-like values under IEEE 754
        # semantics, and that self-inequality behavior is preserved by every
        # numeric type we're likely to see here (float, numpy scalars,
        # pandas NaN), so this catches NaN without needing an isinstance
        # check that would miss numpy.float32 (not a Python float subclass).
        if date is None or close is None or close != close:
            out.append({
                "ticker": ticker, "date": date, "status": "UNKNOWN",
                "reason": "missing date or close", "daily_total_return": None,
            })
            prev_close = None          # break the chain; do NOT bridge the gap
            continue

        ret = None
        if prev_close is not None:
            try:
                ret = daily_total_return(prev_close, close, row.get("dividend", 0.0) or 0.0)
            except ValueError:
                ret = None

        out.append({
            "ticker": ticker,
            "date": date,
            "event_time": bar_event_time(date),
            "available_time": bar_available_time(date),
            "open": row.get("open"), "high": row.get("high"),
            "low": row.get("low"), "close": close,
            "volume": row.get("volume"),
            "dividend": row.get("dividend", 0.0) or 0.0,
            "daily_total_return": ret,
            "status": "OK" if ret is not None else "NO_PRIOR_CLOSE",
        })
        prev_close = close
    return out


def fetch_daily_bars_yfinance(ticker: str, start: str, end: str) -> list[dict[str, Any]]:
    """
    Live fetch. Requires network + `pip install yfinance`. Run on Tyler's machine.

    Deliberately thin: it only shapes provider output into raw rows. All
    correctness logic lives in normalize_bars() so it is testable offline
    against fixtures, with no network and no API key.
    """
    import yfinance as yf  # imported lazily so this module loads without the dep

    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        return []
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    try:
        divs = yf.Ticker(ticker).dividends
    except Exception:
        divs = None

    rows = []
    for idx, r in df.iterrows():
        d = idx.strftime("%Y-%m-%d")
        div = 0.0
        if divs is not None and len(divs):
            try:
                m = divs[divs.index.strftime("%Y-%m-%d") == d]
                div = float(m.iloc[0]) if len(m) else 0.0
            except Exception:
                div = 0.0
        rows.append({
            "date": d, "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None,
            "dividend": div,
        })
    return rows
