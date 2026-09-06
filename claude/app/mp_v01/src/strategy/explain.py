"""Deterministic justifications and drill-downs. No language model or future outcomes."""
from __future__ import annotations
import copy
import json
import math
from typing import Any
from common.validation import digest

EXPLANATION_VERSION = "1.1.0"


def _finite(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def build_explanation(*, ticker: str, variant: str, direction: str,
                      composite_score: float | None, contract: dict[str, Any],
                      components_scaled: dict[str, Any], weights: dict[str, Any],
                      selection_policy: dict[str, Any], selection_metrics: dict[str, Any],
                      decision_date: str, **context: Any) -> dict[str, Any]:
    contributions = []
    for name, weight in sorted((weights or {}).items()):
        value = (components_scaled or {}).get(name)
        contributions.append({"indicator": name, "scaled_value": value, "weight": weight,
                              "weighted_contribution": (value * weight
                               if _finite(value) and _finite(weight) else None)})
    ranked = sorted((d for d in contributions if d["weighted_contribution"] is not None),
                    key=lambda d: (-abs(d["weighted_contribution"]), d["indicator"]))
    top = ranked[:3]
    total = sum(d["weighted_contribution"] for d in ranked)
    drivers = ", ".join(f"{d['indicator'].replace('_', ' ')} {d['weighted_contribution']:+.2f}"
                        for d in top[:2]) or "no usable indicator contributions"
    if not _finite(composite_score) or not contract:
        short = f"{ticker}: ABSTAIN. {context.get('reason') or 'No eligible contract or complete signal.'}"
    else:
        short = (f"{ticker} scored {composite_score:+.2f} ({direction.lower()}): {drivers}. "
                 f"{contract.get('expiration')} {contract.get('strike')} {str(contract.get('type')).lower()}, "
                 f"{contract.get('dte')} DTE, selected by {selection_policy.get('mode', 'unknown')}. "
                 "Paper hypothesis; not a profit guarantee.")
    details = {"version": EXPLANATION_VERSION, "decision_date": decision_date,
               "ticker": ticker, "variant": variant, "direction": direction,
               "composite_score": composite_score, "top_weighted_drivers": top,
               "indicator_contributions": contributions, "contribution_sum": total,
               "score_matches_components": (_finite(composite_score) and len(ranked) == len(contributions)
                                             and abs(total - composite_score) <= 0.000051),
               "all_scaled_indicators": components_scaled, "weights": weights,
               "contract": contract, "selection_policy": selection_policy,
               "selection_metrics": selection_metrics, "context": context,
               "interpretation": "Weighted contributions explain the rule, not causal effects or calibrated profit probabilities."}
    # Own the data: later mutation of caller dictionaries cannot rewrite this explanation.
    details = json.loads(json.dumps(details, sort_keys=True, default=str, allow_nan=False))
    return {"short_justification": short, "details": details,
            "details_fingerprint_sha256": digest(details)}


def attach_explanation(pick: dict[str, Any], sources: dict | None = None) -> dict[str, Any]:
    p = copy.deepcopy(pick)
    p["explanation"] = build_explanation(
        ticker=p.get("ticker", "UNKNOWN"), variant=p.get("variant", "UNKNOWN"),
        direction=p.get("direction", "UNKNOWN"), composite_score=p.get("composite_score"),
        contract=p.get("contract") or {}, components_scaled=p.get("components_scaled") or {},
        weights=p.get("weights") or {}, selection_policy=p.get("selection_policy") or {},
        selection_metrics=p.get("selection_metrics") or {}, decision_date=p.get("decision_date", ""),
        raw_indicators=p.get("components_raw") or {}, reason=p.get("reason"),
        gate_decision=p.get("gate_decision", "ABSTAIN"), gate_failed=p.get("gate_failed", []),
        selection_audit=p.get("selection_audit"), source_files=sources or {},
        signal_target="heuristic_absolute_direction; relative_strength_evaluated_separately",
        exit_policy=p.get("exit_policy"), edge_status=p.get("edge_status", "NOT_DEMONSTRATED"),
        external_context=p.get("external_context"), run_mode=p.get("run_mode", "FORWARD_RESEARCH"))
    p["short_justification"] = p["explanation"]["short_justification"]
    return p


def verify_explanation(value: dict[str, Any]) -> bool:
    try:
        return value["details_fingerprint_sha256"] == digest(value["details"])
    except (KeyError, ValueError, TypeError):
        return False
