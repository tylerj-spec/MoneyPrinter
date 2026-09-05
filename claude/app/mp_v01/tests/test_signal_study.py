from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from datetime import date, timedelta

from harness import test, assert_raises, run_all
from backtest.signal_study import (
    Observation, best_threshold, build_observations, folds_from_splits,
    make_threshold_learner, rank_ic_by_component, run_study, spearman, weighted_score,
)
from backtest.walkforward import Split, TradingCalendar, make_splits


def _weekdays(start: str, end: str) -> TradingCalendar:
    d, last, days = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= last:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return TradingCalendar(tuple(days))


# ---------- Spearman ----------
@test
def spearman_is_one_on_a_monotone_relationship_of_any_shape():
    """Rank correlation, not Pearson: the components are scaled by arbitrary
    constants, so a monotone transform must not change the answer."""
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(spearman(xs, [1.0, 2.0, 3.0, 4.0, 5.0]) - 1.0) < 1e-12
    assert abs(spearman(xs, [1.0, 8.0, 27.0, 64.0, 125.0]) - 1.0) < 1e-12, "cubed is still monotone"
    assert abs(spearman(xs, [5.0, 4.0, 3.0, 2.0, 1.0]) + 1.0) < 1e-12

@test
def spearman_is_none_rather_than_zero_when_undefined():
    """A constant column has no ranking. Returning 0.0 would report 'measured,
    no relationship' for something that was never measurable."""
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert spearman([1.0, 2.0], [1.0, 2.0]) is None, "two points is not a correlation"
    assert_raises(ValueError, spearman, [1.0, 2.0, 3.0], [1.0, 2.0])

@test
def tied_values_get_average_ranks_rather_than_an_invented_order():
    a = spearman([1.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    b = spearman([1.0, 1.0, 2.0, 3.0], [2.0, 1.0, 3.0, 4.0])
    assert abs(a - b) < 1e-12, "swapping tied inputs must not change the answer"


# ---------- threshold fit ----------
@test
def the_threshold_sweep_matches_an_exhaustive_scan_including_ties():
    """The sweep exists only for speed - the noise floor refits it hundreds of
    times per fold. If it ever disagrees with the naive scan it is not an
    optimisation, it is a different model."""
    def naive(scores, labels):
        cands = sorted(set(scores)) or [0.0]
        best_t, best_acc = cands[0], -1
        for t in cands:
            acc = sum(int((s > t) == bool(y)) for s, y in zip(scores, labels))
            if acc > best_acc:
                best_acc, best_t = acc, t
        return best_t
    rng = random.Random(3)
    for trial in range(200):
        n = rng.randint(1, 40)
        # A coarse grid on half the trials, to force the tie-group path.
        scores = [rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0]) if trial % 2 else rng.gauss(0, 1)
                  for _ in range(n)]
        labels = [rng.randint(0, 1) for _ in range(n)]
        assert naive(scores, labels) == best_threshold(scores, labels), (scores, labels)

@test
def a_learner_that_ignores_labels_would_make_the_null_decorative():
    """The permutation null only means something if the fitted thing moves when
    the labels move. This pins that the threshold actually responds."""
    fit = make_threshold_learner({"a": 1.0})
    X = [{"a": v} for v in (-2.0, -1.0, 0.0, 1.0, 2.0)]
    up = fit(X, [0, 0, 0, 1, 1], X)
    down = fit(X, [1, 1, 0, 0, 0], X)
    assert up != down, "predictions must change when the training labels change"

@test
def weighted_score_treats_a_missing_component_as_absent_not_as_zero_signal():
    assert weighted_score({"a": 1.0}, {"a": 1.0, "b": 1.0}) == 1.0


# ---------- observations ----------
def _bars(n: int, start: str = "2024-01-01") -> list[dict]:
    d = date.fromisoformat(start)
    out, px = [], 100.0
    while len(out) < n:
        if d.weekday() < 5:
            px *= 1.001
            out.append({"date": d.isoformat(), "close": round(px, 4),
                        "daily_total_return": 0.001})
        d += timedelta(days=1)
    return out

def _labels(bars: list[dict], usable_from: int = 0) -> list[dict]:
    return [{"decision_date": b["date"], "y": i % 2,
             "excess_log_return": 0.001 * (1 if i % 2 else -1),
             "usable": i >= usable_from} for i, b in enumerate(bars)]

@test
def an_observation_needs_every_component_and_a_resolved_label():
    """A missing component means insufficient history. Filling it with zero would
    invent a neutral reading the data never produced."""
    bars = _bars(80)
    labels = _labels(bars)
    def compute(_bars, _date):
        return {"scaled": {"a": 0.5, "b": None}}
    assert build_observations({"X": bars}, {"X": labels}, compute,
                              required=("a", "b")) == []
    def complete(_bars, _date):
        return {"scaled": {"a": 0.5, "b": -0.25}}
    got = build_observations({"X": bars}, {"X": labels}, complete, required=("a", "b"))
    assert len(got) == len(bars)
    assert got[0].features == {"a": 0.5, "b": -0.25}

@test
def an_unusable_label_is_dropped_rather_than_scored():
    bars = _bars(40)
    labels = _labels(bars, usable_from=10)
    got = build_observations({"X": bars}, {"X": labels},
                             lambda b, d: {"scaled": {"a": 0.1}}, required=("a",))
    assert len(got) == 30, len(got)

@test
def the_benchmark_is_excluded_because_its_excess_return_is_zero_by_definition():
    """SPY's excess return against SPY is identically zero, so including it feeds
    the model a column of labels that mean nothing."""
    bars = _bars(30)
    data = {"SPY": bars, "MSFT": bars}
    labels = {"SPY": _labels(bars), "MSFT": _labels(bars)}
    got = build_observations(data, labels, lambda b, d: {"scaled": {"a": 0.1}},
                             required=("a",), exclude=("SPY",))
    assert {o.ticker for o in got} == {"MSFT"}

@test
def observations_come_back_in_decision_order():
    bars = _bars(20)
    got = build_observations({"B": bars, "A": bars}, {"B": _labels(bars), "A": _labels(bars)},
                             lambda b, d: {"scaled": {"a": 0.1}}, required=("a",))
    assert got == sorted(got, key=lambda o: (o.decision_date, o.ticker))


# ---------- folds ----------
@test
def observations_inside_the_purge_gap_belong_to_neither_half():
    """The whole point of a purge is that those decisions are used by nobody.
    A fold builder that quietly assigned them to training would undo the fix."""
    cal = _weekdays("2024-01-01", "2024-12-31")
    obs = [Observation("X", d.isoformat(), {"a": 0.0}, 1, 0.01) for d in cal.sessions]
    sp = Split(0, cal[0], cal[9], cal[15], cal[25])       # 5 sessions purged: 10..14
    folds = folds_from_splits(obs, [sp])
    assert len(folds) == 1
    used = len(folds[0].train_y) + len(folds[0].test_y)
    assert used == 10 + 11, used
    assert used < 26, "the purged sessions must not appear in either half"

@test
def a_fold_with_an_empty_half_is_dropped_rather_than_evaluated():
    cal = _weekdays("2024-01-01", "2024-06-30")
    obs = [Observation("X", cal[i].isoformat(), {"a": 0.0}, 1, 0.01) for i in range(5)]
    sp = Split(0, cal[0], cal[4], cal[10], cal[20])       # test window has no observations
    assert folds_from_splits(obs, [sp]) == []


# ---------- rank IC ----------
@test
def a_component_that_ranks_perfectly_reads_ic_one_and_a_reversed_one_reads_minus_one():
    cal = _weekdays("2024-01-01", "2024-12-31")
    splits = make_splits(cal, train_sessions=20, test_sessions=10)
    obs = []
    for i, d in enumerate(cal.sessions):
        r = (i % 7) / 7.0 - 0.5
        obs.append(Observation("X", d.isoformat(),
                               {"aligned": r, "backwards": -r}, 1 if r > 0 else 0, r))
    ic = {r.component: r for r in rank_ic_by_component(obs, splits, ["aligned", "backwards"])}
    assert abs(ic["aligned"].mean - 1.0) < 1e-9, ic["aligned"].mean
    assert abs(ic["backwards"].mean + 1.0) < 1e-9, ic["backwards"].mean
    assert ic["aligned"].hit_rate == 1.0

@test
def a_mean_ic_whose_sign_flips_across_folds_is_reported_as_such():
    """A mean of +0.03 built from +0.30 and -0.24 is not a weak edge, it is no
    edge measured twice. hit_rate is the cheapest way to see that."""
    from backtest.signal_study import ICResult
    r = ICResult("x", [0.30, -0.24])
    assert r.mean > 0 and r.hit_rate == 0.5, (r.mean, r.hit_rate)
    steady = ICResult("y", [0.05, 0.06, 0.04, 0.05])
    assert steady.hit_rate == 1.0


# ---------- the study ----------
@test
def a_study_on_no_observations_raises_instead_of_returning_an_empty_verdict():
    """A backtest on nothing is not a smaller backtest. It is a number with no
    meaning that will nonetheless be read as one."""
    cal = _weekdays("2024-01-01", "2024-12-31")
    assert_raises(ValueError, run_study, [], cal, [])

@test
def a_calendar_too_short_for_one_fold_raises_from_make_splits():
    cal = _weekdays("2024-01-01", "2024-03-01")
    obs = [Observation("X", cal[i].isoformat(), {"a": 0.0}, 1, 0.01) for i in range(len(cal))]
    assert_raises(ValueError, run_study, obs, cal, [])

@test
def the_study_reads_no_edge_on_labels_that_are_pure_noise():
    """The property that makes the whole harness worth trusting: point it at
    nothing and it must say nothing. If this ever reports SIGNAL_CANDIDATE,
    every result the tool has ever produced is suspect."""
    class V:
        name, description = "coin", "a coin flip"
        weights = {"a": 1.0}
        def normalised_weights(self): return dict(self.weights)

    rng = random.Random(19)
    cal = _weekdays("2023-01-02", "2025-06-30")
    obs = [Observation("X", d.isoformat(), {"a": rng.gauss(0, 1)},
                       rng.randint(0, 1), rng.gauss(0, 0.01)) for d in cal.sessions]
    study = run_study(obs, cal, [V()], train_sessions=120, test_sessions=30,
                      n_permutations=40, seed=5)
    rep = study["variants"][0].report
    assert "SIGNAL_CANDIDATE" not in rep.verdict(), rep.render()

@test
def every_variant_is_measured_on_the_same_folds():
    """Comparing variants only means something if they saw identical data. A
    variant quietly running on a different subset is how a spread of weightings
    turns into a selection artefact."""
    class V:
        def __init__(self, name, w): self.name, self.weights = name, w
        description = ""
        def normalised_weights(self): return dict(self.weights)

    rng = random.Random(4)
    cal = _weekdays("2023-01-02", "2024-12-31")
    obs = [Observation("X", d.isoformat(), {"a": rng.gauss(0, 1), "b": rng.gauss(0, 1)},
                       rng.randint(0, 1), rng.gauss(0, 0.01)) for d in cal.sessions]
    study = run_study(obs, cal, [V("one", {"a": 1.0}), V("two", {"b": 1.0})],
                      train_sessions=120, test_sessions=30, n_permutations=10)
    counts = {v.variant: (v.n_train, v.n_test) for v in study["variants"]}
    assert len(set(counts.values())) == 1, counts


if __name__ == "__main__":
    sys.exit(0 if run_all("SIGNAL STUDY: rank IC, folds, noise floor") else 1)
