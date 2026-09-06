"""Small auditable numerical challenger, not an autonomous trading algorithm.

Train-only scaling and coefficients, validation-only calibration, chronological
holdout evaluation. Label availability purges overlapping boundary labels.
No LLM, downloads, broker connection or active-strategy edits occur here.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
import random
from common.validation import digest, number, utc
from research.experiments import Experiment, promotion_decision


def _sigmoid(z):
    z = max(-40., min(40., z))
    return 1. / (1. + math.exp(-z))


def _weights(rows):
    counts = Counter((r["decision_utc"][:10], r["ticker"]) for r in rows)
    w = [1 / counts[(r["decision_utc"][:10], r["ticker"])] for r in rows]
    total = sum(w)
    return [x / total for x in w]


def fit(rows, features):
    if len(rows) < 20:
        raise ValueError("at least 20 usable training observations required")
    weights = _weights(rows)
    means = [sum(w * r["features"][f] for w, r in zip(weights, rows)) for f in features]
    scales = [max(1e-6, math.sqrt(sum(w * (r["features"][f] - mean) ** 2 for w, r in zip(weights, rows))))
              for f, mean in zip(features, means)]
    x = [[max(-10, min(10, (r["features"][f] - m) / s)) for f, m, s in zip(features, means, scales)] for r in rows]
    y = [float(r["net_return"] > 0) for r in rows]
    p = min(.99, max(.01, sum(w * value for w, value in zip(weights, y))))
    intercept, coefficients = math.log(p / (1 - p)), [0.] * len(features)
    for _ in range(400):
        residual = [(_sigmoid(intercept + sum(c * v for c, v in zip(coefficients, row))) - target) * weight
                    for row, target, weight in zip(x, y, weights)]
        intercept -= .08 * sum(residual)
        coefficients = [c - .08 * (sum(err * row[j] for err, row in zip(residual, x)) + .05 * c)
                        for j, c in enumerate(coefficients)]
    return {"features": list(features), "means": means, "scales": scales, "coefficients": coefficients,
            "intercept": intercept, "training_base_rate": p, "calibration_intercept": 0., "calibration_slope": 1.,
            "train_rows_sha256": digest(rows), "model_version": "regularized-logistic-1"}


def raw_score(model, row):
    x = [max(-10, min(10, (row["features"][f] - m) / s)) for f, m, s in zip(model["features"], model["means"], model["scales"])]
    return model["intercept"] + sum(c * v for c, v in zip(model["coefficients"], x))


def predict(model, row):
    return _sigmoid(model["calibration_intercept"] + model["calibration_slope"] * raw_score(model, row))


def calibrate(model, rows):
    if len(rows) < 20:
        raise ValueError("at least 20 validation observations required")
    a, b = 0., 1.
    weights = _weights(rows)
    logits = [raw_score(model, r) for r in rows]
    for _ in range(200):
        errs = [w * (_sigmoid(a + b * z) - float(r["net_return"] > 0)) for w, z, r in zip(weights, logits, rows)]
        a -= .03 * sum(errs)
        b = max(0., min(3., b - .03 * (sum(e * z for e, z in zip(errs, logits)) + .05 * (b - 1))))
    return {**model, "calibration_intercept": a, "calibration_slope": b,
            "validation_rows_sha256": digest(rows)}


def _metrics(rows, probabilities, enter):
    groups = defaultdict(list)
    for row, p, trade in zip(rows, probabilities, enter):
        groups[row["decision_utc"][:10]].append((row, p, trade))
    returns, brier, logloss = [], [], []
    for day, values in sorted(groups.items()):
        returns.append(sum(r["net_return"] if trade else 0 for r, _, trade in values) / len(values))
        brier.append(sum((p - float(r["net_return"] > 0)) ** 2 for r, p, _ in values) / len(values))
        logloss.append(sum(-math.log(max(1e-12, p if r["net_return"] > 0 else 1 - p)) for r, p, _ in values) / len(values))
    cumulative = peak = worst = 0.
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return {"observations": len(groups), "rows": len(rows), "net_expectancy": sum(returns) / len(returns),
            "max_drawdown": worst, "drawdown_units": "CUMULATIVE_RETURN_UNITS_NOT_PORTFOLIO_PERCENT",
            "brier": sum(brier) / len(brier), "log_loss": sum(logloss) / len(logloss),
            "trade_rate": sum(enter) / len(enter), "date_returns": returns,
            "cohort_sha256": digest([r["row_id"] for r in rows])}


def _bootstrap_lower(differences, *, seed=61, block=5):
    rng = random.Random(seed)
    means, n = [], len(differences)
    for _ in range(500):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(differences[(start + i) % n] for i in range(block))
        means.append(sum(sample[:n]) / n)
    return sorted(means)[int(.025 * len(means))]


def run_study(spec: Experiment, rows: list[dict], *, registered_utc: str,
              evaluated_utc: str | None = None, allow_synthetic: bool = False) -> dict:
    spec.validate()
    evaluated_utc = evaluated_utc or datetime.now(timezone.utc).isoformat()
    evaluated, registered = utc(evaluated_utc), utc(registered_utc)
    if registered > evaluated:
        raise ValueError("registration cannot be in the future")
    ids, usable, rejected = set(), [], Counter()
    for original in rows:
        try:
            if not original.get("row_id") or original["row_id"] in ids:
                raise ValueError("duplicate or missing row identity")
            ids.add(original["row_id"])
            decision, available, label = (utc(original[k]) for k in ("decision_utc", "feature_available_utc", "label_available_utc"))
            if available > decision or label <= decision or label > evaluated:
                rejected["unavailable_or_invalid_time"] += 1
                continue
            if original.get("provenance") != "OBSERVED_QUOTES":
                if not (allow_synthetic and original.get("provenance") == "SYNTHETIC_DEMO"):
                    rejected["not_observed_quotes"] += 1
                    continue
            values = {f: number(original["features"][f], f) for f in spec.features}
            net = number(original["net_return"], "net_return")
            if not isinstance(original.get("ticker"), str) or not original["ticker"]:
                raise ValueError("ticker required")
            usable.append({"row_id": original["row_id"], "ticker": original["ticker"],
                           "decision_utc": decision.isoformat(), "label_available_utc": label.isoformat(),
                           "features": values, "net_return": net})
        except (KeyError, ValueError, TypeError, OverflowError):
            rejected["invalid_row"] += 1
    usable.sort(key=lambda r: (utc(r["decision_utc"]), r["row_id"]))
    def segment(start, end, next_start=None):
        selected = []
        for r in usable:
            day = r["decision_utc"][:10]
            if start <= day <= end:
                if next_start and r["label_available_utc"][:10] >= next_start:
                    rejected["label_overlap_purged"] += 1
                else:
                    selected.append(r)
        return selected
    train = segment(spec.train_start, spec.train_end, spec.validation_start)
    validation = segment(spec.validation_start, spec.validation_end, spec.holdout_start)
    holdout = segment(spec.holdout_start, spec.holdout_end)
    counts = {"train": len(train), "validation": len(validation), "holdout": len(holdout)}
    if any(count < 20 for count in counts.values()):
        return {"status": "INSUFFICIENT_ELIGIBLE_DATA", "counts": counts, "rejected": dict(rejected),
                "active_weights_changed": False, "experiment": spec.record()}
    model = calibrate(fit(train, spec.features), validation)
    p = [predict(model, r) for r in holdout]
    baseline = _metrics(holdout, [model["training_base_rate"]] * len(holdout), [True] * len(holdout))
    challenger = _metrics(holdout, p, [value >= .5 for value in p])
    difference = [a - b for a, b in zip(challenger["date_returns"], baseline["date_returns"])]
    challenger["bootstrap_lower_improvement"] = _bootstrap_lower(difference)
    challenger["fresh_forward_holdout"] = registered.date().isoformat() < spec.holdout_start and not allow_synthetic
    can_review, reasons = promotion_decision(baseline=baseline, challenger=challenger)
    if allow_synthetic:
        can_review = False
        reasons.append("synthetic_smoke_test_not_evidence")
    return {"status": "RESEARCH_REPORT", "experiment": spec.record(), "model": model,
            "counts": counts, "rejected": dict(rejected), "baseline": baseline, "challenger": challenger,
            "manual_review_candidate": can_review, "review_blockers": reasons,
            "holdout_predictions": [{"row_id": r["row_id"], "probability_positive_return": prob,
                                     "actual_positive": r["net_return"] > 0} for r, prob in zip(holdout, p)],
            "active_weights_changed": False, "registered_utc": registered_utc,
            "limitations": ["Assumes accurate observed-quote provenance; local hashes are not attestations.",
                            "Probabilities are research estimates, not validated trade recommendations.",
                            "Date blocks reduce dependence; multiple experiments still require multiplicity control.",
                            "A retrospective registration is not a fresh untouched forward holdout.",
                            "Return-unit drawdown is not a capital-constrained portfolio drawdown."]}
