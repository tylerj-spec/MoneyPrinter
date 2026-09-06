"""Adversarial regression tests for optimistic paper-trading failure modes."""
from __future__ import annotations
import copy
import random
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from backtest.replay import run_replay
from paper.quotes import quote_quality, simulate_fill
from replay_options import demo_dataset


def _q(*, bid=1.0, ask=1.1, size=3, observed="2026-09-04T15:00:02Z", **kw):
    q = {"contract_id": "C", "source": "ADVERSARIAL_FIXTURE", "feed_type": "OPRA",
         "delayed": False, "bid": bid, "ask": ask, "bid_size": size, "ask_size": size,
         "size_units": "CONTRACTS", "observed_utc": observed, "available_utc": observed}
    q.update(kw)
    return q


def test_randomized_fills_never_improve_beyond_observed_side_or_displayed_size():
    rng = random.Random(20260906)
    for _ in range(250):
        bid = round(rng.uniform(.05, 20), 2)
        ask = round(bid + rng.uniform(.01, 1.0), 2)
        size = rng.randint(0, 20)
        consumed = rng.randint(0, size + 3)
        qty = rng.randint(1, 25)
        q = _q(bid=bid, ask=ask, size=size)
        for side, limit, expected in (("BUY", ask, ask), ("SELL", bid, bid)):
            fill = simulate_fill(q, side=side, limit_price=limit, quantity=qty,
                                 submitted_utc="2026-09-04T15:00:00Z",
                                 execution_utc="2026-09-04T15:00:02Z", consumed_size=consumed)
            available = max(0, size - consumed)
            if available == 0:
                assert fill["status"] == "NO_FILL"
            else:
                assert fill["quantity"] == min(qty, available)
                assert fill["price"] == expected
                assert fill["quantity"] <= available


def test_quote_quality_adversarial_mutations_fail_closed():
    cutoff = "2026-09-04T15:00:30Z"
    mutations = [
        {"available_utc": "2026-09-04T15:00:31Z"},
        {"observed_utc": "2026-09-04T15:00:31Z", "available_utc": "2026-09-04T15:00:31Z"},
        {"observed_utc": "2026-09-04T14:58:00Z", "available_utc": "2026-09-04T14:58:00Z"},
        {"delayed": True}, {"feed_type": "INDICATIVE"}, {"size_units": "SHARES"},
        {"bid": 2.0, "ask": 1.0}, {"ask": 0}, {"bid_size": -1}, {"ask_size": 1.5},
    ]
    for mutation in mutations:
        good, reason = quote_quality(_q(**mutation), decision_utc=cutoff)
        assert not good, (mutation, reason)


def test_twenty_random_future_outcome_mutations_cannot_change_frozen_decisions():
    base = demo_dataset()
    original = run_replay(base, generated_utc="2026-09-05T12:00:00Z")
    rng = random.Random(77)
    for _ in range(20):
        changed = copy.deepcopy(base)
        factor = rng.uniform(.1, 3.0)
        for q in changed["quotes"]:
            if q["observed_utc"] > "2026-09-04T15:00:00Z":
                q["bid"] = max(.01, q["bid"] * factor)
                q["ask"] = max(q["bid"] + .01, q["ask"] * factor)
        replay = run_replay(changed, generated_utc="2026-09-05T12:00:00Z")
        assert replay["pick_records"] == original["pick_records"]


def test_regression_runners_are_bounded_and_noise_demo_uses_fast_verified_threshold():
    root = Path(__file__).resolve().parents[4]
    run_all = (root / "claude/app/mp_v01/run_all.py").read_text("utf-8")
    run_tests = (root / "run_tests.py").read_text("utf-8")
    noise = (root / "claude/app/mp_v01/demo/run_noise_floor.py").read_text("utf-8")
    assert "timeout=STEP_TIMEOUT_SECONDS" in run_all
    assert "timeout=SUITE_TIMEOUT_SECONDS" in run_tests
    assert "best_threshold(scores, train_y)" in noise
    assert "for cand in" not in noise
