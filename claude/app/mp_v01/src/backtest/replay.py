"""Point-in-time replay guards for historical option observations."""
from __future__ import annotations
from datetime import datetime
from typing import Iterable

def _dt(v:str): return datetime.fromisoformat(v.replace("Z","+00:00"))

def eligible_observations(rows:Iterable[dict], *, decision_utc:str, contract_id:str)->list[dict]:
    """Return only observations demonstrably available by the simulated decision."""
    cutoff=_dt(decision_utc); out=[]
    for r in rows:
        if r.get("contract_id")!=contract_id: continue
        try: observed=_dt(str(r["observed_utc"])); available=_dt(str(r["available_utc"]))
        except (KeyError,ValueError,TypeError): continue
        if observed.tzinfo is None or available.tzinfo is None or cutoff.tzinfo is None: continue
        if observed<=cutoff and available<=cutoff: out.append(r)
    return sorted(out,key=lambda r:(r["observed_utc"],r["available_utc"]))

def latest_predecision_quote(rows:Iterable[dict], *, decision_utc:str, contract_id:str):
    eligible=eligible_observations(rows,decision_utc=decision_utc,contract_id=contract_id)
    return eligible[-1] if eligible else None

def replay_fill(quote:dict|None, *, side:str, multiplier:int=100):
    """Conservative one-contract replay price; no quote means no invented fill."""
    if quote is None: return {"status":"NO_FILL","reason":"no_eligible_predecision_quote"}
    if multiplier<=0: return {"status":"NO_FILL","reason":"invalid_multiplier"}
    key="ask" if side=="BUY" else "bid"
    try: price=float(quote[key])
    except (KeyError,TypeError,ValueError): return {"status":"NO_FILL","reason":"missing_executable_side"}
    if price<=0: return {"status":"NO_FILL","reason":"invalid_executable_price"}
    return {"status":"FILLED","price":price,"multiplier":multiplier,
            "observed_utc":quote.get("observed_utc"),"available_utc":quote.get("available_utc"),
            "source":quote.get("source")}
