"""Black-Scholes pricing, implied volatility and Greeks."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import math
from harness import test, run_all, assert_raises
from options.greeks import (
    CALL, PUT, MAX_VOL, black_scholes_price, greeks, implied_volatility,
    norm_cdf, years_to_expiry,
)

# Textbook reference case: S=100, K=100, T=1, r=5%, sigma=20%, no dividend.
REF = dict(S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, q=0.0)


@test
def price_matches_the_published_reference_value():
    """If this drifts, every Greek below is measuring the wrong model."""
    c = black_scholes_price(**REF, kind=CALL)
    p = black_scholes_price(**REF, kind=PUT)
    assert abs(c - 10.4506) < 1e-4, c
    assert abs(p - 5.5735) < 1e-4, p


@test
def norm_cdf_matches_known_quantiles():
    for x, expected in ((0.0, 0.5), (1.0, 0.8413447), (-1.96, 0.0249979)):
        assert abs(norm_cdf(x) - expected) < 1e-6, (x, norm_cdf(x))


@test
def put_call_parity_holds():
    """C - P = S*e^-qT - K*e^-rT. An identity, not an approximation: it must
    hold for every strike and dividend yield or the formulas disagree."""
    for K in (60.0, 100.0, 145.0):
        for q in (0.0, 0.03):
            args = dict(S=100.0, K=K, T=0.75, r=0.04, sigma=0.3, q=q)
            c = black_scholes_price(**args, kind=CALL)
            p = black_scholes_price(**args, kind=PUT)
            lhs = c - p
            rhs = 100.0 * math.exp(-q * 0.75) - K * math.exp(-0.04 * 0.75)
            assert abs(lhs - rhs) < 1e-9, (K, q, lhs, rhs)


@test
def delta_stays_inside_its_theoretical_bounds():
    for K in (50.0, 100.0, 200.0):
        args = dict(S=100.0, K=K, T=0.5, r=0.04, sigma=0.35, q=0.0)
        assert 0.0 <= greeks(**args, kind=CALL).delta <= 1.0
        assert -1.0 <= greeks(**args, kind=PUT).delta <= 0.0


@test
def deep_in_and_out_of_the_money_deltas_saturate():
    near = dict(T=0.25, r=0.04, sigma=0.25, q=0.0)
    assert greeks(S=100.0, K=10.0, **near, kind=CALL).delta > 0.99
    assert greeks(S=100.0, K=1000.0, **near, kind=CALL).delta < 0.01
    assert greeks(S=100.0, K=1000.0, **near, kind=PUT).delta < -0.99


@test
def gamma_and_vega_are_positive_and_identical_across_call_and_put():
    """Both are second-order in the same underlying distribution, so a call and
    a put on identical terms must share them exactly."""
    args = dict(S=100.0, K=105.0, T=0.4, r=0.03, sigma=0.28, q=0.01)
    c, p = greeks(**args, kind=CALL), greeks(**args, kind=PUT)
    assert c.gamma > 0 and c.vega > 0
    assert abs(c.gamma - p.gamma) < 1e-12
    assert abs(c.vega - p.vega) < 1e-12


@test
def a_long_option_loses_value_to_time():
    """Theta is reported per calendar day, so it should be small and negative
    for an at-the-money long - not the per-year figure."""
    g = greeks(**REF, kind=CALL)
    assert g.theta < 0, g.theta
    assert abs(g.theta) < 0.1, f"theta {g.theta} looks per-year, not per-day"


@test
def vega_is_scaled_per_volatility_point_not_per_unit():
    """A 1-point vol move on a 1-year ATM contract is worth well under $1;
    the raw per-unit figure would be near $37 and silently 100x too big."""
    g = greeks(**REF, kind=CALL)
    assert 0.2 < g.vega < 0.6, g.vega
    bumped = black_scholes_price(**{**REF, "sigma": 0.21}, kind=CALL)
    assert abs((bumped - black_scholes_price(**REF, kind=CALL)) - g.vega) < 5e-3


@test
def implied_volatility_round_trips():
    for sigma in (0.10, 0.25, 0.80):
        for K, kind in ((90.0, CALL), (100.0, CALL), (115.0, PUT)):
            args = dict(S=100.0, K=K, T=0.6, r=0.04, q=0.01)
            price = black_scholes_price(**args, sigma=sigma, kind=kind)
            solved = implied_volatility(price, **args, kind=kind)
            assert solved is not None, (sigma, K, kind)
            assert abs(solved - sigma) < 1e-4, (sigma, solved)


@test
def a_quote_outside_no_arbitrage_bounds_is_unsolvable_not_clamped():
    """No volatility produces these prices. Returning an endpoint would look
    like a real IV; returning None says what is actually true."""
    args = dict(S=100.0, K=100.0, T=0.5, r=0.04, q=0.0)
    assert implied_volatility(99.9, **args, kind=CALL) is None   # above S
    assert implied_volatility(0.0, **args, kind=CALL) is None    # non-positive
    # Priced beyond the solver's ceiling, so it cannot be bracketed.
    too_rich = black_scholes_price(**args, sigma=MAX_VOL * 1.5, kind=CALL)
    assert implied_volatility(too_rich, **args, kind=CALL) is None


@test
def degenerate_inputs_fail_closed_rather_than_returning_a_number():
    bad = [
        dict(S=100.0, K=100.0, T=0.0, r=0.04, sigma=0.2),    # expired
        dict(S=100.0, K=100.0, T=-1.0, r=0.04, sigma=0.2),   # past expiry
        dict(S=100.0, K=100.0, T=0.5, r=0.04, sigma=0.0),    # no volatility
        dict(S=0.0, K=100.0, T=0.5, r=0.04, sigma=0.2),      # worthless underlying
        dict(S=100.0, K=0.0, T=0.5, r=0.04, sigma=0.2),      # zero strike
        dict(S=float("nan"), K=100.0, T=0.5, r=0.04, sigma=0.2),
        dict(S=100.0, K=100.0, T=0.5, r=float("inf"), sigma=0.2),
    ]
    for args in bad:
        assert black_scholes_price(**args, kind=CALL) is None, args
        assert greeks(**args, kind=CALL) is None, args


@test
def an_unknown_option_type_is_rejected_loudly():
    """A typo'd side must not silently price as a call."""
    assert_raises(ValueError, black_scholes_price, 100.0, 100.0, 0.5, 0.04, 0.2, 0.0, "CALLS")
    assert_raises(ValueError, greeks, 100.0, 100.0, 0.5, 0.04, 0.2, 0.0, "c")


@test
def time_to_expiry_counts_calendar_days_and_refuses_expired_contracts():
    assert abs(years_to_expiry("2026-01-01", "2026-01-31") - 30 / 365.0) < 1e-12
    assert years_to_expiry("2026-01-01", "2026-01-01") is None   # expires today
    assert years_to_expiry("2026-02-01", "2026-01-01") is None   # already expired
    assert years_to_expiry("garbage", "2026-01-01") is None
    assert years_to_expiry("2026-01-01", None) is None


if __name__ == "__main__":
    sys.exit(0 if run_all("OPTIONS - BLACK-SCHOLES, IV AND GREEKS") else 1)
