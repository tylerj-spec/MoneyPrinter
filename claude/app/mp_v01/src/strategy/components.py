"""
Score components, computed from point-in-time bars only.

Every function here takes a list of bars ENDING AT THE LAST BAR AVAILABLE at the
decision time, and looks only backwards. None of them may see the decision day's
own close: a daily bar is not consumable at its own close (see
adapters/yahoo_daily.BAR_AVAILABILITY_LAG_HOURS), so the caller is responsible
for slicing, and slice_available() below does it in one place so no caller has
to remember.

NOTHING HERE IS VALIDATED. These are ordinary technical constructions - trailing
return, distance from a moving average, realised volatility, drawdown. Not one
of them has a measured rank information coefficient against forward excess
return in this repository. They are hypotheses to be tested by forward paper
logging, and are named `components` rather than `signals` for that reason.

Each returns None rather than a number when there is not enough history. A None
propagates all the way to an abstention, never to a zero.
"""
from __future__ import annotations

import math
from typing import Any, Sequence


def slice_available(bars: Sequence[dict[str, Any]], decision_date: str) -> list[dict[str, Any]]:
    """Bars a decision on `decision_date` may legitimately see.

    Strictly before the decision date. Including the decision day's own bar
    would be one full day of lookahead in every component below.
    """
    return [b for b in bars
            if b.get("date") and b["date"] < decision_date and b.get("close") is not None]


def _closes(bars: Sequence[dict[str, Any]], n: int) -> list[float] | None:
    if len(bars) < n:
        return None
    out = [b["close"] for b in bars[-n:]]
    return out if all(isinstance(c, (int, float)) and c > 0 for c in out) else None


def _returns(bars: Sequence[dict[str, Any]], n: int) -> list[float] | None:
    """Daily TOTAL returns, which already include distributions."""
    if len(bars) < n:
        return None
    out = [b.get("daily_total_return") for b in bars[-n:]]
    return out if all(isinstance(r, (int, float)) for r in out) else None


def trailing_return(bars: Sequence[dict[str, Any]], lookback: int) -> float | None:
    """Compounded total return over the last `lookback` sessions."""
    rets = _returns(bars, lookback)
    if rets is None:
        return None
    total = 1.0
    for r in rets:
        total *= (1.0 + r)
    return total - 1.0


def distance_from_sma(bars: Sequence[dict[str, Any]], window: int) -> float | None:
    """(close - SMA) / SMA. Positive means trading above its own average."""
    closes = _closes(bars, window)
    if closes is None:
        return None
    sma = sum(closes) / len(closes)
    return (closes[-1] / sma - 1.0) if sma > 0 else None


def realised_volatility(bars: Sequence[dict[str, Any]], window: int = 20) -> float | None:
    """Annualised standard deviation of daily total returns."""
    rets = _returns(bars, window)
    if rets is None or len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def drawdown_from_high(bars: Sequence[dict[str, Any]], window: int = 252) -> float | None:
    """How far below its trailing high the close sits. Zero or negative."""
    closes = _closes(bars, min(window, len(bars))) if bars else None
    if not closes:
        return None
    peak = max(closes)
    return (closes[-1] / peak - 1.0) if peak > 0 else None


def volatility_percentile(bars: Sequence[dict[str, Any]], window: int = 20,
                          history: int = 252) -> float | None:
    """Where current realised vol sits in its own trailing distribution, 0..1.

    Compares a stock only against itself, which avoids needing a cross-sectional
    universe and keeps the figure meaningful with three tickers.
    """
    if len(bars) < window + history // 4:
        return None
    series = []
    for end in range(window, len(bars) + 1):
        v = realised_volatility(bars[max(0, end - history):end][-window:], window)
        if v is not None:
            series.append(v)
    if len(series) < 20:
        return None
    current = series[-1]
    return sum(1 for v in series if v <= current) / len(series)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute(bars: Sequence[dict[str, Any]], decision_date: str) -> dict[str, Any]:
    """All components for one instrument at one decision date.

    Raw values are kept alongside the scaled ones so a reader can check the
    transform rather than trust it. Scaling constants are stated, arbitrary,
    and unvalidated - they set the units, not the conclusion.
    """
    avail = slice_available(bars, decision_date)
    r20 = trailing_return(avail, 20)
    r60 = trailing_return(avail, 60)
    sma50 = distance_from_sma(avail, 50)
    vol = realised_volatility(avail, 20)
    vol_pct = volatility_percentile(avail)
    dd = drawdown_from_high(avail)

    return {
        "bars_available": len(avail),
        "last_available_date": avail[-1]["date"] if avail else None,
        "last_available_close": avail[-1]["close"] if avail else None,
        "raw": {"return_20d": r20, "return_60d": r60, "distance_from_sma50": sma50,
                "realised_vol_20d": vol, "vol_percentile": vol_pct,
                "drawdown_from_252d_high": dd},
        # Scaled to roughly [-1, 1]. A 10% 20-day move saturates momentum; a 10%
        # gap from the 50-day saturates trend; a 20% drawdown saturates that.
        "scaled": {
            "momentum_20d": _clip(r20 / 0.10) if r20 is not None else None,
            "momentum_60d": _clip(r60 / 0.20) if r60 is not None else None,
            "trend_50d": _clip(sma50 / 0.10) if sma50 is not None else None,
            # Low volatility scores positive: high vol widens option spreads and
            # raises premium, both of which work against a long-premium buyer.
            "low_volatility": _clip(1.0 - 2.0 * vol_pct) if vol_pct is not None else None,
            # A deep drawdown scores positive as a mean-reversion tilt. Whether
            # that is predictive is exactly what has not been established.
            "reversion": _clip(-dd / 0.20) if dd is not None else None,
        },
    }
