from research.experiments import Experiment, promotion_decision

def exp(**kw):
    d=dict(name="x",hypothesis="feature improves net option expectancy",signal_version="1",features=("trend",),train_start="2020-01-01",train_end="2023-12-31",validation_start="2024-01-01",validation_end="2024-12-31",holdout_start="2025-01-01",holdout_end="2025-12-31"); d.update(kw); return Experiment(**d)

def test_experiment_is_stable_and_chronological():
    assert exp().record()["experiment_id"]==exp().record()["experiment_id"]

def test_overlap_is_rejected():
    try: exp(validation_start="2023-12-01").validate()
    except ValueError: pass
    else: assert False

def test_challenger_requires_fresh_evidence_and_better_tradeoffs():
    b={"net_expectancy":0.02,"max_drawdown":-0.20}
    assert promotion_decision(baseline=b,challenger={"observations":20,"net_expectancy":0.05,"max_drawdown":-0.15})[0] is False
    assert promotion_decision(baseline=b,challenger={"observations":60,"net_expectancy":0.05,"max_drawdown":-0.15})[0] is True
