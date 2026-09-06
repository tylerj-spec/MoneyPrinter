from paper.ledger import PaperAccount, PaperPosition, proposal_context, apply_long_fill


def test_whole_contract_cost_and_account_context():
    account = PaperAccount(equity=1000, cash=1000)
    c = proposal_context(account, entry_price=2, quantity=1)
    assert c["proposed_max_loss"] == 200 and c["position_pct"] == .2


def test_fill_reduces_cash_and_records_position():
    account = apply_long_fill(PaperAccount(1000, 1000), PaperPosition("1", "SPY", "c", 1, 2))
    assert account.cash == 800 and account.open_risk() == 200


def test_duplicate_and_insufficient_cash_rejected():
    p = PaperPosition("1", "SPY", "c", 1, 2)
    account = apply_long_fill(PaperAccount(1000, 1000), p)
    for a in (account, PaperAccount(100, 100)):
        try:
            apply_long_fill(a, p)
        except ValueError:
            pass
        else:
            assert False
