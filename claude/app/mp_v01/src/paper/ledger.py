from dataclasses import dataclass,asdict
@dataclass(frozen=True)
class PaperPosition:
 position_id:str; ticker:str; contract_id:str; quantity:int; entry_price:float; multiplier:int=100
 def max_loss(self): return round(self.quantity*self.entry_price*self.multiplier,2)
@dataclass(frozen=True)
class PaperAccount:
 equity:float; cash:float; positions:tuple[PaperPosition,...]=()
 def open_risk(self): return round(sum(p.max_loss() for p in self.positions),2)
 def snapshot(self): return {"equity":self.equity,"cash":self.cash,"open_positions":len(self.positions),"open_risk":self.open_risk(),"positions":[asdict(p) for p in self.positions]}
def proposal_context(account,*,entry_price,quantity=1,multiplier=100):
 if account.equity<=0 or account.cash<0 or quantity<=0 or entry_price<=0 or multiplier<=0: raise ValueError("invalid paper-account or proposal values")
 proposed=entry_price*quantity*multiplier
 return {"position_pct":proposed/account.equity,"portfolio_heat_pct":(account.open_risk()+proposed)/account.equity,"open_positions":len(account.positions),"proposed_max_loss":round(proposed,2),"cash_sufficient":account.cash>=proposed}
def apply_long_fill(account,position):
 if any(p.position_id==position.position_id for p in account.positions): raise ValueError("duplicate paper position id")
 cost=position.max_loss()
 if cost>account.cash: raise ValueError("insufficient paper cash")
 return PaperAccount(account.equity,round(account.cash-cost,2),account.positions+(position,))
