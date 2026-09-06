from paper.ledger import PaperAccount, PaperPosition, apply_long_fill, proposal_context

def test_proposal_context_counts_existing_heat():
    old=PaperPosition("old","SPY","c1",1,1.0)
    a=PaperAccount(1000,900,(old,))
    c=proposal_context(a,entry_price=2.0)
    assert c["position_pct"]==0.2 and c["portfolio_heat_pct"]==0.3 and c["open_positions"]==1

def test_fill_is_cash_constrained_and_duplicate_safe():
    a=PaperAccount(1000,500)
    p=PaperPosition("p1","SPY","c2",1,2.0)
    b=apply_long_fill(a,p)
    assert b.cash==300 and len(b.positions)==1
    try: apply_long_fill(b,p)
    except ValueError as e: assert "duplicate" in str(e)
    else: assert False

def test_small_account_does_not_fake_fractional_contract():
    c=proposal_context(PaperAccount(1000,1000),entry_price=2.0)
    assert c["proposed_max_loss"]==200 and c["position_pct"]==0.2
