"""Deterministic risk gates. Models may propose; this module decides."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
class Decision(str,Enum):
    PASS="PASS"; WATCH="WATCH"; PAPER_TRADE_CANDIDATE="PAPER_TRADE_CANDIDATE"
@dataclass(frozen=True)
class RiskLimits:
    min_independent_events:int=2; min_evidence_confidence:float=0.60; max_position_pct:float=0.02; max_portfolio_heat_pct:float=0.06; max_open_positions:int=5; min_dte:int=21; max_dte:int=60; max_relative_spread:float=0.10; min_open_interest:int=500; min_daily_volume:int=50; require_defined_risk:bool=True; min_edge_after_costs:float=0.0
@dataclass
class GateResult:
    decision:Decision; reasons:list[str]=field(default_factory=list); failed_gates:list[str]=field(default_factory=list)
    def to_dict(self): return {"decision":self.decision.value,"reasons":self.reasons,"failed_gates":self.failed_gates}
def evaluate(candidate:dict,limits:RiskLimits=RiskLimits())->GateResult:
    failed=[]; reasons=[]
    def need(k):
        v=candidate.get(k)
        if v is None: failed.append(f"missing:{k}"); reasons.append(f"{k} is required"); return None
        if not isinstance(v,(int,float)) or isinstance(v,bool): failed.append(f"invalid_type:{k}"); reasons.append(f"{k} must be numeric"); return None
        if not math.isfinite(float(v)): failed.append(f"invalid_numeric:{k}"); reasons.append(f"{k} must be finite"); return None
        return v
    n=need("independent_events"); conf=need("evidence_confidence")
    if n is not None and n<limits.min_independent_events: failed.append("insufficient_independent_evidence")
    if conf is not None and conf<limits.min_evidence_confidence: failed.append("low_evidence_confidence")
    if candidate.get("unresolved_contradictions"): failed.append("unresolved_contradictions")
    if candidate.get("cutoff_violations"): failed.append("cutoff_violation")
    dte=need("dte"); spread=need("relative_spread"); oi=need("open_interest"); vol=need("daily_volume")
    if dte is not None and not limits.min_dte<=dte<=limits.max_dte: failed.append("dte_out_of_band")
    if spread is not None and spread>limits.max_relative_spread: failed.append("spread_too_wide")
    if oi is not None and oi<limits.min_open_interest: failed.append("insufficient_open_interest")
    if vol is not None and vol<limits.min_daily_volume: failed.append("insufficient_volume")
    if limits.require_defined_risk and candidate.get("defined_risk") is not True: failed.append("undefined_risk_structure")
    edge=need("expected_edge_after_costs")
    if edge is not None and edge<=limits.min_edge_after_costs: failed.append("no_edge_after_costs")
    size=need("position_pct"); heat=need("portfolio_heat_pct"); open_n=need("open_positions")
    if size is not None and size>limits.max_position_pct: failed.append("position_too_large")
    if heat is not None and heat>limits.max_portfolio_heat_pct: failed.append("portfolio_heat_exceeded")
    if open_n is not None and (open_n<0 or int(open_n)!=open_n): failed.append("invalid_open_positions")
    elif open_n is not None and open_n>=limits.max_open_positions: failed.append("max_positions_reached")
    if not failed:return GateResult(Decision.PAPER_TRADE_CANDIDATE,["all gates passed"],[])
    hard={"cutoff_violation","no_edge_after_costs","undefined_risk_structure","position_too_large","portfolio_heat_exceeded","max_positions_reached","invalid_open_positions"}
    if any(f in hard or f.startswith(("missing:","invalid_numeric:","invalid_type:")) for f in failed): return GateResult(Decision.PASS,reasons,failed)
    return GateResult(Decision.WATCH,reasons,failed)
