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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

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


# ---------------------------------------------------------------------------
# Split-adjustment guard
# ---------------------------------------------------------------------------
# daily_total_return() has no split term, which is correct ONLY while Yahoo's
# Close stays split-adjusted. That was verified once, by hand, against NVDA in
# June 2024. A verified assumption about a third-party scraper is still an
# assumption, and the failure is silent: if Close ever goes genuinely raw, every
# split in the history becomes a fabricated ~-90% move and the label contract
# scores it as a real crash.
#
# So the assumption is now checked on every fetch, against the split dates Yahoo
# reports alongside the bars.
#
# HOW IT DISCRIMINATES. On the effective date of an r-for-1 split:
#   Close is split-adjusted (what we need) -> close/prev_close is an ordinary day
#   Close is raw                           -> close/prev_close is almost exactly 1/r
# A 10-for-1 split makes those 1.00-ish versus 0.10 — not a close call. The
# check therefore fires on the arithmetic signature of an unadjusted series, not
# on the size of a move, which is what makes it precise where a plain magnitude
# threshold is blunt: a genuine -40% earnings collapse is a real observation and
# is left alone, because a -40% day is nowhere near 1/r for any material split.
#
# WHAT IT DOES NOT COVER. Small splits (3-for-2, 5-for-4) are skipped and
# reported as IMMATERIAL: their unadjusted signature is a -33% or -20% day, which
# a real session can produce, so flagging them would cost false positives on
# exactly the tail events a risk model needs. That is an acceptable hole because
# the hazard being defended against is a VENDOR-WIDE change in behaviour, and a
# vendor that starts serving raw closes serves them for the big splits too.
#
# THE REPAIR IS SURGICAL. In a raw series only the return that straddles the
# split is wrong; every other day is priced in one consistent regime and is
# fine. So a flagged date loses its return and keeps its prices, and the chain
# continues into the new regime rather than being broken.

SPLIT_MATERIALITY = 2.0        # only ratios >= 2:1 or <= 1:2 are discriminable
SPLIT_MATCH_TOLERANCE = 0.15   # how near 1/r the observed ratio must sit


@dataclass(frozen=True)
class SplitCheck:
    """One split, and what the bars around it say about vendor adjustment."""
    date: str
    ratio: float
    verdict: str          # ADJUSTED | UNADJUSTED | IMMATERIAL | UNCHECKABLE
    observed_ratio: float | None
    expected_if_raw: float | None
    detail: str

    @property
    def failed(self) -> bool:
        return self.verdict == "UNADJUSTED"


def _split_map(raw_rows: list[dict[str, Any]],
               splits: Mapping[str, float] | Iterable[tuple[str, float]] | None,
               ) -> dict[str, float]:
    """Split ratios by effective date, from an explicit map or off the rows."""
    if splits is None:
        return {r["date"]: float(r["split"]) for r in raw_rows
                if r.get("date") and r.get("split")}
    items = splits.items() if isinstance(splits, Mapping) else splits
    return {str(d): float(r) for d, r in items if r}


def check_split_adjustment(
    raw_rows: list[dict[str, Any]],
    splits: Mapping[str, float] | Iterable[tuple[str, float]] | None = None,
    *,
    materiality: float = SPLIT_MATERIALITY,
    tolerance: float = SPLIT_MATCH_TOLERANCE,
) -> list[SplitCheck]:
    """Report, for every known split, whether the bars look split-adjusted.

    Pure: takes rows and ratios, touches no network. `splits` defaults to the
    `split` key on the rows themselves, which is what the live fetch attaches.
    """
    dated = [r for r in raw_rows if r.get("date") is not None]
    position = {r["date"]: i for i, r in enumerate(dated)}
    out: list[SplitCheck] = []

    for day, ratio in sorted(_split_map(raw_rows, splits).items()):
        if day not in position:
            continue                      # split outside the fetched window
        if not (ratio > 0):
            out.append(SplitCheck(day, ratio, "UNCHECKABLE", None, None,
                                  f"non-positive split ratio {ratio}"))
            continue
        if 1.0 / materiality < ratio < materiality:
            out.append(SplitCheck(day, ratio, "IMMATERIAL", None, 1.0 / ratio,
                                  f"ratio {ratio:g} is inside {1/materiality:g}..{materiality:g}; "
                                  f"an unadjusted series would look like an ordinary "
                                  f"large move here, so this split cannot discriminate"))
            continue

        i = position[day]
        prev = dated[i - 1] if i > 0 else None
        close, prev_close = dated[i].get("close"), (prev or {}).get("close")
        usable = (prev is not None
                  and isinstance(close, (int, float)) and close == close and close > 0
                  and isinstance(prev_close, (int, float)) and prev_close == prev_close
                  and prev_close > 0)
        if not usable:
            out.append(SplitCheck(day, ratio, "UNCHECKABLE", None, 1.0 / ratio,
                                  "no usable prior close to compare against"))
            continue

        observed = close / prev_close
        expected_if_raw = 1.0 / ratio
        if abs(observed - expected_if_raw) <= tolerance * expected_if_raw:
            out.append(SplitCheck(
                day, ratio, "UNADJUSTED", observed, expected_if_raw,
                f"close moved {observed - 1:+.1%} across a {ratio:g}-for-1 split, "
                f"which is the {expected_if_raw - 1:+.1%} a RAW series produces. "
                f"Yahoo's Close appears to be no longer split-adjusted; "
                f"daily_total_return() has no split term and would score this as "
                f"a real move."))
        else:
            out.append(SplitCheck(
                day, ratio, "ADJUSTED", observed, expected_if_raw,
                f"close moved {observed - 1:+.1%} across a {ratio:g}-for-1 split, "
                f"nothing like the {expected_if_raw - 1:+.1%} of a raw series"))
    return out


def normalize_bars(raw_rows: list[dict[str, Any]], ticker: str,
                   splits: Mapping[str, float] | Iterable[tuple[str, float]] | None = None,
                   ) -> list[dict[str, Any]]:
    """
    Convert raw provider rows into records carrying the four-timestamp contract.

    Expected raw row keys: date (YYYY-MM-DD), open, high, low, close, volume,
    and optionally dividend.

    Missing or unusable values are marked UNKNOWN. Nothing is interpolated,
    carried forward, or estimated - see the module docstring in the ingestion
    package. A gap is reported, never patched.

    SPLITS. When split ratios are available - passed in, or carried on the rows
    as `split`, which is what the live fetch attaches - each material one is
    checked against the bars around it. A date whose move matches the signature
    of an UNADJUSTED series keeps its prices but loses its return, marked
    SPLIT_UNADJUSTED, because that return would otherwise be a fabricated ~-90%
    crash that the label contract scores as real. The chain continues through
    it: only the straddling return is unusable, the days either side of the
    split are each priced consistently within their own regime.
    """
    checks = check_split_adjustment(raw_rows, splits)
    suspect = {c.date: c for c in checks if c.failed}

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

        record = {
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
        }
        if date in suspect:
            c = suspect[date]
            record["daily_total_return"] = None
            record["status"] = "SPLIT_UNADJUSTED"
            record["split_ratio"] = c.ratio
            record["reason"] = c.detail
        out.append(record)
        prev_close = close
    return out


# ---------------------------------------------------------------------------
# Option chain rows
# ---------------------------------------------------------------------------
# Lives here, pure, for the same reason normalize_bars() does: the correctness
# is testable offline against fixtures, and only the fetching needs a network.
# It was previously inline in fetch_data.py, where it could not be tested and
# where a single malformed row aborted an entire ticker's chain.

def _finite(value: Any) -> float | None:
    """A real number, or None. NaN and non-numerics become None.

    `x != x` is true only for NaN under IEEE 754, and that holds for every
    numeric type likely to arrive here - float, numpy scalars, pandas NA - so
    it catches NaN without an isinstance check that numpy.float32 would slip
    past.

    The trap this exists for: NaN is TRUTHY, so the natural-looking
    `float(row.get("volume") or 0)` evaluates to NaN rather than 0, and the
    int() of that raises. Yahoo returns NaN volume and open interest on
    illiquid contracts routinely, so that is not an edge case, it is Tuesday.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _count(value: Any) -> int | None:
    """A non-negative whole count, or None when it was not reported.

    None rather than 0: a contract Yahoo declines to report volume for has
    UNKNOWN volume, and calling that zero is inventing an observation. The
    liquidity screen treats missing as failing, so nothing is loosened by it.
    """
    f = _finite(value)
    return int(f) if f is not None and f >= 0 else None


def normalize_option_row(row: Any, *, side: str, expiration: str) -> dict[str, Any]:
    """One contract from a Yahoo chain, with every number coerced or refused.

    `row` is anything with .get() - a pandas Series or a plain dict - so the
    tests do not need pandas.
    """
    get = row.get
    strike = _finite(get("strike"))
    bid, ask = _finite(get("bid")), _finite(get("ask"))
    usable = (bid is not None and ask is not None
              and bid > 0 and ask > 0 and ask >= bid and strike is not None)
    return {
        "contract_symbol": get("contractSymbol") or None,
        "type": side,
        "expiration": expiration,
        "strike": strike,
        "bid": bid if usable else None,
        "ask": ask if usable else None,
        "mid": round((bid + ask) / 2, 4) if usable else None,
        "volume": _count(get("volume")),
        "open_interest": _count(get("openInterest")),
        # Yahoo's own IV, kept for comparison only. The Greeks are solved from
        # the quote in options/greeks.py rather than trusting this field.
        "implied_volatility": _finite(get("impliedVolatility")) or None,
        "status": "OK" if usable else "UNKNOWN",
    }


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

    tk = yf.Ticker(ticker)
    try:
        divs = tk.dividends
    except Exception:
        divs = None

    # Splits are fetched for the guard above, not for price maths - there is no
    # split term in daily_total_return() and there should not be one while Close
    # stays adjusted. They are the evidence that it still is.
    try:
        spl = tk.splits
    except Exception:
        spl = None

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
        split = 0.0
        if spl is not None and len(spl):
            try:
                m = spl[spl.index.strftime("%Y-%m-%d") == d]
                split = float(m.iloc[0]) if len(m) else 0.0
            except Exception:
                split = 0.0
        rows.append({
            "date": d, "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None,
            "dividend": div, "split": split,
        })
    return rows
