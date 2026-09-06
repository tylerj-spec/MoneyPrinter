from pathlib import Path
import copy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from research.experiments import Experiment, promotion_decision
from research.study import run_study
from refine_model import demo


def exp(**kw):
    d = dict(name="x", hypothesis="feature improves net option expectancy", signal_version="1", features=("trend_50d",), train_start="2020-01-01", train_end="2023-12-31", validation_start="2024-01-01", validation_end="2024-12-31", holdout_start="2025-01-01", holdout_end="2025-12-31")
    d.update(kw)
    return Experiment(**d)


def test_experiment_is_stable_and_chronological():
    assert exp().record()["experiment_id"] == exp().record()["experiment_id"]


def test_overlap_and_outcome_features_are_rejected():
    for e in (exp(validation_start="2023-12-01"), exp(features=("future_return",))):
        try:
            e.validate()
        except ValueError:
            pass
        else:
            assert False


def test_challenger_requires_fresh_evidence_and_better_tradeoffs():
    b = {"net_expectancy": .02, "max_drawdown": -.20, "cohort_sha256": "same"}
    c = {"observations": 60, "net_expectancy": .05, "max_drawdown": -.15, "cohort_sha256": "same", "fresh_forward_holdout": True, "bootstrap_lower_improvement": .01}
    assert promotion_decision(baseline=b, challenger=c)[0]
    for change in ({"observations": 20}, {"net_expectancy": float("nan")}, {"max_drawdown": float("inf")}, {"fresh_forward_holdout": False}, {"cohort_sha256": "other"}, {"observations": True}):
        assert not promotion_decision(baseline=b, challenger={**c, **change})[0]


def test_future_holdout_outcomes_do_not_change_fit_or_calibration():
    spec, rows = demo()
    changed = copy.deepcopy(rows)
    for r in changed:
        if r["decision_utc"][:10] >= spec.holdout_start:
            r["net_return"] *= -1
    a = run_study(spec, rows, registered_utc="2026-01-01T00:00:00Z", evaluated_utc="2026-02-01T00:00:00Z", allow_synthetic=True)
    b = run_study(spec, changed, registered_utc="2026-01-01T00:00:00Z", evaluated_utc="2026-02-01T00:00:00Z", allow_synthetic=True)
    assert a["model"] == b["model"]
    assert a["challenger"] != b["challenger"]
    assert a["challenger"]["brier"] < a["baseline"]["brier"]
    assert a["active_weights_changed"] is False and not a["manual_review_candidate"]


def test_unavailable_labels_and_unverified_prices_do_not_train():
    spec, rows = demo()
    for r in rows:
        r["provenance"] = "MODELLED_ONLY"
    report = run_study(spec, rows, registered_utc="2026-01-01T00:00:00Z")
    assert report["status"] == "INSUFFICIENT_ELIGIBLE_DATA"
    assert report["rejected"]["not_observed_quotes"] == len(rows)


def test_boundary_overlapping_labels_are_purged():
    spec, rows = demo()
    for r in rows[:5]:
        r["label_available_utc"] = "2024-07-03T00:00:00Z"
    report = run_study(spec, rows, registered_utc="2026-01-01T00:00:00Z", allow_synthetic=True)
    assert report["rejected"]["label_overlap_purged"] >= 5
