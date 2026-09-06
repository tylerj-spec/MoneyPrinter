"""Pre-registered experiment definitions for chronological model refinement."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
import hashlib, json

@dataclass(frozen=True)
class Experiment:
    name:str; hypothesis:str; signal_version:str; features:tuple[str,...]
    train_start:str; train_end:str; validation_start:str; validation_end:str
    holdout_start:str; holdout_end:str; parameters:tuple[tuple[str,str],...]=()
    def validate(self):
        dates=[date.fromisoformat(x) for x in (self.train_start,self.train_end,self.validation_start,self.validation_end,self.holdout_start,self.holdout_end)]
        if not (dates[0]<=dates[1]<dates[2]<=dates[3]<dates[4]<=dates[5]):
            raise ValueError("train, validation and untouched holdout must be chronological and non-overlapping")
        if not self.features: raise ValueError("features must be preregistered")
        return self
    def record(self):
        self.validate(); d=asdict(self); raw=json.dumps(d,sort_keys=True,separators=(",",":")); d["experiment_id"]=hashlib.sha256(raw.encode()).hexdigest(); return d

def promotion_decision(*, baseline:dict, challenger:dict, minimum_observations:int=50)->tuple[bool,list[str]]:
    """Conservative mechanical screen; never claims statistical significance."""
    reasons=[]
    n=int(challenger.get("observations") or 0)
    if n<minimum_observations: reasons.append("insufficient_fresh_holdout_observations")
    for key in ("net_expectancy","max_drawdown"):
        if baseline.get(key) is None or challenger.get(key) is None: reasons.append(f"missing:{key}")
    if not reasons:
        if challenger["net_expectancy"]<=baseline["net_expectancy"]: reasons.append("expectancy_not_improved")
        if challenger["max_drawdown"]<baseline["max_drawdown"]: reasons.append("drawdown_worse")
    return not reasons,reasons
