"""Stable, auditable explanation records for paper option hypotheses."""
from __future__ import annotations

import hashlib
import json
from typing import Any

EXPLANATION_VERSION = "1.0.0"


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def build_explanation(*, ticker: str, variant: str, direction: str,
                      composite_score: float, contract: dict[str, Any],
                      components_scaled: dict[str, Any], weights: dict[str, Any],
                      selection_policy: dict[str, Any], selection_metrics: dict[str, Any],
                      decision_date: str) -> dict[str, Any]:
    """Return a short justification plus a machine-auditable drill-down record.

    The short text is derived only from fields frozen at decision time. The
    details object is deliberately structured so a UI/report can link from the
    sentence to the exact indicators and contract-selection measurements.
    """
    ranked = []
    for name, weight in (weights or {}).items():
        value = (components_scaled or {}).get(name)
        if isinstance(value, (int, float)) and isinstance(weight, (int, float)):
            ranked.append((abs(float(weight) * float(value)), name, float(value), float(weight)))
    ranked.sort(reverse=True)
    drivers = [
        {"indicator": name, "scaled_value": round(value, 6), "weight": round(weight, 6),
         "weighted_contribution": round(value * weight, 6)}
        for _importance, name, value, weight in ranked[:3]
    ]
    driver_text = ", ".join(
        f"{d['indicator'].replace('_', ' ')} {d['weighted_contribution']:+.2f}" for d in drivers
    ) or "no scored indicator contribution available"
    ctype = str(contract.get("type") or "option").lower()
    short = (
        f"{ticker} scored {composite_score:+.2f} ({direction.lower()}); strongest weighted "
        f"drivers: {driver_text}. Selected {contract.get('expiration')} "
        f"{contract.get('strike')} {ctype}, delta {contract.get('delta')}, "
        f"{contract.get('dte')} DTE, under the {selection_policy.get('mode', 'unknown')} policy."
    )
    details = {
        "version": EXPLANATION_VERSION,
        "decision_date": decision_date,
        "ticker": ticker,
        "variant": variant,
        "direction": direction,
        "composite_score": composite_score,
        "top_weighted_drivers": drivers,
        "all_scaled_indicators": components_scaled,
        "weights": weights,
        "contract": contract,
        "selection_policy": selection_policy,
        "selection_metrics": selection_metrics,
    }
    return {
        "short_justification": short,
        "details": details,
        "details_fingerprint_sha256": _stable_hash(details),
    }
