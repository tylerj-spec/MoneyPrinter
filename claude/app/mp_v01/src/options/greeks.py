"""
Black-Scholes pricing, implied volatility, and Greeks. Standard library only.

WHY THIS EXISTS
Yahoo's option chain does not publish Greeks. It publishes a two-sided quote,
volume, open interest, and its own implied-volatility figure. So Greeks have to
be derived, and this module derives them in ONE documented way rather than
importing a black box.

WHAT IS OBSERVED AND WHAT IS MODELLED - the distinction that matters:

    OBSERVED   bid, ask, strike, expiration, volume, open interest,
               and the underlying close from the point-in-time bar store
    MODELLED   implied volatility solved from the mid price, and every Greek

A Greek is not a measurement. It is the output of a model whose assumptions -
lognormal returns, constant volatility, continuous hedging, no early exercise -
are all false in varying degrees for a real listed option. American exercise is
the one that bites hardest here: these are European formulas, so an in-the-money
American put's delta and theta are wrong by an amount this module does not
estimate. Treat everything modelled as an approximation with a known bias, not
a fact about the contract.

WHY NOT USE YAHOO'S IV
Yahoo publishes `impliedVolatility`, computed by Yahoo, with an undocumented
model, undocumented rate, and undocumented dividend assumption. Feeding that
into these formulas would stack this model on top of an unknown one and label
the result a Greek. Instead the IV is solved here from the observed mid, so the
whole chain is: observed quote -> this model -> these Greeks. Yahoo's figure is
still carried alongside in the export, precisely so the two can be compared -
a large divergence is a data-quality signal worth seeing.

FAILING CLOSED
Every function returns None rather than a number it cannot stand behind: an
expired or zero-volatility contract, a non-positive price, a quote outside
no-arbitrage bounds. A None propagates to a blank cell and an UNKNOWN status.
Nothing here ever substitutes a plausible-looking default.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Solver bounds. A contract whose mid implies volatility outside this range is
# reported unsolvable rather than clamped to an endpoint - a clamped IV looks
# like a real number and is not.
MIN_VOL = 1e-4
MAX_VOL = 5.0            # 500% annualised
_SOLVER_TOLERANCE = 1e-6
_SOLVER_MAX_ITER = 200

CALL = "CALL"
PUT = "PUT"


def norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (stdlib, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _finite_positive(*vals: float) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v > 0 for v in vals)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float):
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t


def black_scholes_price(S: float, K: float, T: float, r: float, sigma: float,
                        q: float = 0.0, kind: str = CALL) -> float | None:
    """European option price. None if the inputs cannot support a price.

    S underlying, K strike, T years to expiry, r risk-free rate,
    sigma annualised volatility, q continuous dividend yield.
    """
    if not _finite_positive(S, K, T, sigma):
        return None
    if not all(math.isfinite(v) for v in (r, q)):
        return None
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    if kind == CALL:
        return S * disc_q * norm_cdf(d1) - K * disc_r * norm_cdf(d2)
    if kind == PUT:
        return K * disc_r * norm_cdf(-d2) - S * disc_q * norm_cdf(-d1)
    raise ValueError(f"kind must be {CALL!r} or {PUT!r}, got {kind!r}")


def implied_volatility(price: float, S: float, K: float, T: float, r: float,
                       q: float = 0.0, kind: str = CALL) -> float | None:
    """Solve for the volatility that reproduces `price`. None if unsolvable.

    Bisection, not Newton. Vega collapses to nearly zero for deep in- and
    out-of-the-money contracts, and Newton's step divides by it - which turns a
    hard-to-price contract into a confident wrong answer. Bisection just fails
    to bracket and returns None, which is the honest outcome.
    """
    if not _finite_positive(price, S, K, T):
        return None
    if not all(math.isfinite(v) for v in (r, q)):
        return None

    # No-arbitrage bounds. A quote outside these cannot be produced by ANY
    # volatility, so there is nothing to solve for - usually a stale or
    # mispriced quote on an illiquid contract.
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    if kind == CALL:
        lo_bound, hi_bound = max(S * disc_q - K * disc_r, 0.0), S * disc_q
    elif kind == PUT:
        lo_bound, hi_bound = max(K * disc_r - S * disc_q, 0.0), K * disc_r
    else:
        raise ValueError(f"kind must be {CALL!r} or {PUT!r}, got {kind!r}")
    if not (lo_bound - _SOLVER_TOLERANCE <= price <= hi_bound + _SOLVER_TOLERANCE):
        return None

    lo, hi = MIN_VOL, MAX_VOL
    p_lo = black_scholes_price(S, K, T, r, lo, q, kind)
    p_hi = black_scholes_price(S, K, T, r, hi, q, kind)
    if p_lo is None or p_hi is None:
        return None
    if not (p_lo - _SOLVER_TOLERANCE <= price <= p_hi + _SOLVER_TOLERANCE):
        return None          # not bracketed within the permitted vol range

    for _ in range(_SOLVER_MAX_ITER):
        mid = 0.5 * (lo + hi)
        p_mid = black_scholes_price(S, K, T, r, mid, q, kind)
        if p_mid is None:
            return None
        if abs(p_mid - price) < _SOLVER_TOLERANCE or (hi - lo) < _SOLVER_TOLERANCE:
            return mid
        if p_mid < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class Greeks:
    """Per-contract sensitivities, in the units a trader reads them in.

    delta  per $1 of underlying
    gamma  delta change per $1 of underlying
    theta  per CALENDAR day (the raw formula is per year)
    vega   per 1 volatility POINT (i.e. per 0.01 of sigma)
    rho    per 1 percentage point of rate (i.e. per 0.01 of r)
    """
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

    def as_dict(self) -> dict[str, float]:
        return {"delta": self.delta, "gamma": self.gamma, "theta": self.theta,
                "vega": self.vega, "rho": self.rho}


def greeks(S: float, K: float, T: float, r: float, sigma: float,
           q: float = 0.0, kind: str = CALL) -> Greeks | None:
    """All five Greeks, or None if the inputs cannot support them."""
    if not _finite_positive(S, K, T, sigma):
        return None
    if not all(math.isfinite(v) for v in (r, q)):
        return None
    if kind not in (CALL, PUT):
        raise ValueError(f"kind must be {CALL!r} or {PUT!r}, got {kind!r}")

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    sqrt_t = math.sqrt(T)
    pdf_d1 = norm_pdf(d1)

    gamma = disc_q * pdf_d1 / (S * sigma * sqrt_t)
    vega_per_unit = S * disc_q * pdf_d1 * sqrt_t
    decay = -(S * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if kind == CALL:
        delta = disc_q * norm_cdf(d1)
        theta_per_year = decay - r * K * disc_r * norm_cdf(d2) + q * S * disc_q * norm_cdf(d1)
        rho_per_unit = K * T * disc_r * norm_cdf(d2)
    else:
        delta = -disc_q * norm_cdf(-d1)
        theta_per_year = decay + r * K * disc_r * norm_cdf(-d2) - q * S * disc_q * norm_cdf(-d1)
        rho_per_unit = -K * T * disc_r * norm_cdf(-d2)

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta_per_year / 365.0,   # per calendar day
        vega=vega_per_unit / 100.0,     # per 1 vol point
        rho=rho_per_unit / 100.0,       # per 1 rate point
    )


def years_to_expiry(snapshot_date: str, expiration: str) -> float | None:
    """Calendar-day year fraction. None if the option has already expired.

    Calendar days, not trading days: theta decays over weekends, and the
    discount factor is calendar-based. An option expiring today has no
    remaining optionality this model can price, so it returns None rather
    than a T of zero that would divide by zero downstream.
    """
    from datetime import date
    try:
        d0 = date.fromisoformat(str(snapshot_date)[:10])
        d1 = date.fromisoformat(str(expiration)[:10])
    except (ValueError, TypeError):
        return None
    days = (d1 - d0).days
    return days / 365.0 if days > 0 else None
