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

# Conservative: a session's daily bar is treated as consumable the following
# morning, not at that session's own close. Tighten only with measured evidence
# of actual publication latency.
BAR_AVAILABILITY_LAG_HOURS = 17  # 16:00 ET close -> ~09:00 ET next morning
ET_UTC_OFFSET_HOURS = 4


def bar_available_time(bar_date: str) -> datetime:
    """When a daily bar for `bar_date` could first legitimately be consumed."""
    y, m, d = (int(x) for x in bar_date.split("-"))
    close_et = datetime(y, m, d, 16, 0)
    close_utc = (close_et + timedelta(hours=ET_UTC_OFFSET_HOURS)).replace(tzinfo=timezone.utc)
    return close_utc + timedelta(hours=BAR_AVAILABILITY_LAG_HOURS)


def bar_event_time(bar_date: str) -> datetime:
    """The close the bar describes."""
    y, m, d = (int(x) for x in bar_date.split("-"))
    close_et = datetime(y, m, d, 16, 0)
    return (close_et + timedelta(hours=ET_UTC_OFFSET_HOURS)).replace(tzinfo=timezone.utc)


def daily_total_return(close_prev: float, close: float, dividend: float = 0.0) -> float:
    """Simple daily TOTAL return including distributions.

    Uses raw closes plus the cash distribution rather than vendor-adjusted
    closes. Adjusted-close series are silently rewritten whenever a vendor
    restates adjustment factors, which retroactively changes historical
    features - exactly the silent-revision class the project prohibits.
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
        if date is None or close is None or (isinstance(close, float) and close != close):
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
