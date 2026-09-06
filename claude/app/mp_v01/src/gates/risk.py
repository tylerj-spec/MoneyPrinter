"""Deterministic risk gates. Models may propose; this module decides."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum

class Decision(str, Enum):
    PASS="PASS"; WATCH="WATCH"; PAPER_TRADE_CANDIDATE="PAPER_TRADE_CANDIDATE"

@dataclass(frozen=True)
class RiskLimits:
    min_independent_events:int=2; min_evidence_confidence:float=0.60
    max_position_pct:float=0.02; max_portfolio_heat_pct:float=0.06; max_open_positions:int=5
    min_dte:int=21; max_dte:int=60; max_relative_spread:float=0.10
    min_open_interest:int=500; min_daily_volume:int=50; require_defined_risk:bool=True
    min_edge_after_costs:float=0.0

@dataclass
class GateResult:
    decision:Decision; reasons:list[str]=field(default_factory=list); failed_gates:list[str]=field(default_factory=list)
    def to_dict(self): return {"decision":self.decision.value,"reasons":self.reasons,"failed_gates":self.failed_gates}

def evaluate(candidate:dict, limits:RiskLimits=RiskLimits())->GateResult:
    """Fail closed. A paper candidate requires complete evidence and portfolio context."""
    failed=[]; reasons=[]
    def isnum(v): return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(float(v))
    def need(k):
        v=candidate.get(k)
        if v is None: failed.append(f"missing:{k}"); reasons.append(f"{k} is required"); return None
        if not isnum(v): failed.append(f"invalid_numeric:{k}"); reasons.append(f"{k} must be a finite number"); return None
        return v
    n=need("independent_events")
    if n is not None and n<limits.min_independent_events: failed.append("insufficient_independent_evidence")
    conf=need("evidence_confidence")
    if conf is not None and conf<limits.min_evidence_confidence: failed.append("low_evidence_confidence")
    if candidate.get("unresolved_contradictions"): failed.append("unresolved_contradictions")
    if candidate.get("cutoff_violations"): failed.append("cutoff_violation")
    dte=need("dte")
    if dte is not None and not limits.min_dte<=dte<=limits.max_dte: failed.append("dte_out_of_band")
    spread=need("relative_spread")
    if spread is not None and spread>limits.max_relative_spread: failed.append("spread_too_wide")
    oi=need("open_interest")
    if oi is not None and oi<limits.min_open_interest: failed.append("insufficient_open_interest")
    vol=need("daily_volume")
    if vol is not None and vol<limits.min_daily_volume: failed.append("insufficient_volume")
    defined=candidate.get("defined_risk")
    if limits.require_defined_risk and defined is not True:
        failed.append("undefined_risk_structure"); reasons.append("defined_risk must explicitly be true")
    edge=need("expected_edge_after_costs")
    if edge is not None and edge<=limits.min_edge_after_costs: failed.append("no_edge_after_costs")
    # Portfolio context is mandatory before the word CANDIDATE can be emitted.
    size=need("position_pct")
    if size is not None and size>limits.max_position_pct: failed.append("position_too_large")
    heat=need("portfolio_heat_pct")
    if heat is not None and heat>limits.max_portfolio_heat_pct: failed.append("portfolio_heat_exceeded")
    open_n=need("open_positions")
    if open_n is not None and (open_n<0 or int(open_n)!=open_n): failed.append("invalid_open_positions")
    elif open_n is not None and open_n>=limits.max_open_positions: failed.append("max_positions_reached")
    if not failed: return GateResult(Decision.PAPER_TRADE_CANDIDATE,["all gates passed"],[])
    hard={"cutoff_violation","no_edge_after_costs","undefined_risk_structure","position_too_large","portfolio_heat_exceeded","max_positions_reached","invalid_open_positions"}
    if any(f in hard or f.startswith("missing:") or f.startswith("invalid_numeric:") for f in failed):
        return GateResult(Decision.PASS,reasons,failed)
    return GateResult(Decision.WATCH,reasons,failed)
