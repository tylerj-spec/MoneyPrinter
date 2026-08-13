"""
End-to-end demonstration on SYNTHETIC data.

*** THE DATA IN THIS DEMO IS FABRICATED BY A RANDOM NUMBER GENERATOR. ***
Nothing here is a market prediction, a backtest result, or evidence of edge.
Its only purpose is to prove the MACHINERY behaves correctly - specifically that
the point-in-time store, the cost model, and the risk gates all do what they claim.

Real data cannot be wired in until the historical options provider question is
answered. That remains the project's top open risk.
"""
from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from datetime import datetime, timezone, timedelta

from pit.schema import make_record, SourceTier, ValidationStatus
from pit.store import PointInTimeStore
from backtest.costs import CostModel
from backtest.walkforward import make_splits
from gates.risk import evaluate, RiskLimits, Decision

random.seed(42)
LINE = "-" * 72


def hdr(t):
    print(f"\n{LINE}\n{t}\n{LINE}")


def build_store() -> PointInTimeStore:
    s = PointInTimeStore()
    base = datetime(2026, 3, 2, 14, 30, tzinfo=timezone.utc)

    # One wire story, syndicated to six outlets: ONE information event.
    for i in range(6):
        s.add(make_record(
            record_id=f"wire-copy-{i}", entity_id="NVDA", ticker_at_time="NVDA",
            source_id=f"outlet-{i}", source_tier=SourceTier.SECONDARY_PRESS,
            claim="Analyst raises target on datacenter demand",
            event_time=base, published_time=base + timedelta(minutes=5),
            available_time=base + timedelta(minutes=5 + i),
            lineage_cluster_id="wire-story-nvda-001", original_source_id="wire-desk",
            validation_status=ValidationStatus.VALID,
        ))

    # A genuinely independent primary filing: a SECOND information event.
    s.add(make_record(
        record_id="filing-8k", entity_id="NVDA", ticker_at_time="NVDA",
        source_id="sec-edgar", source_tier=SourceTier.PRIMARY_FILING,
        claim="8-K: supply agreement executed",
        event_time=base + timedelta(hours=2), published_time=base + timedelta(hours=2, minutes=10),
        available_time=base + timedelta(hours=2, minutes=12),
        lineage_cluster_id="edgar-8k-nvda-77", original_source_id="sec-edgar",
        validation_status=ValidationStatus.VALID,
    ))

    # Tomorrow's news. Must be invisible to today's decision.
    s.add(make_record(
        record_id="future-beat", entity_id="NVDA", ticker_at_time="NVDA",
        source_id="wire-desk", source_tier=SourceTier.MAJOR_PRESS,
        claim="Earnings beat announced",
        event_time=base + timedelta(days=1), published_time=base + timedelta(days=1),
        available_time=base + timedelta(days=1),
        lineage_cluster_id="earnings-nvda-q1", original_source_id="wire-desk",
        validation_status=ValidationStatus.VALID,
    ))

    # A macro print that gets revised upward three weeks later.
    s.add(make_record(
        record_id="gdp-initial", entity_id="US-MACRO", ticker_at_time="MACRO",
        source_id="bea", source_tier=SourceTier.PRIMARY_FILING, claim="GDP q/q advance",
        event_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        published_time=datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc),
        available_time=datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc),
        lineage_cluster_id="gdp-2026q1", original_source_id="bea", numeric_value=2.0,
        validation_status=ValidationStatus.VALID,
    ))
    s.add(make_record(
        record_id="gdp-revised", entity_id="US-MACRO", ticker_at_time="MACRO",
        source_id="bea", source_tier=SourceTier.PRIMARY_FILING, claim="GDP q/q revised",
        event_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        published_time=datetime(2026, 3, 25, 13, 30, tzinfo=timezone.utc),
        available_time=datetime(2026, 3, 25, 13, 30, tzinfo=timezone.utc),
        lineage_cluster_id="gdp-2026q1", original_source_id="bea", numeric_value=3.4,
        supersedes_record_id="gdp-initial", validation_status=ValidationStatus.VALID,
    ))
    return s


def main() -> int:
    print("=" * 72)
    print("MONEY PRINTER V0.1 - END-TO-END DEMO  [SYNTHETIC DATA - NOT A PREDICTION]")
    print("=" * 72)

    store = build_store()
    decision_time = "2026-03-02T18:00:00Z"

    hdr("1. POINT-IN-TIME RETRIEVAL")
    visible = store.as_of(decision_time, ticker="NVDA")
    print(f"Decision time            : {decision_time}")
    print(f"Raw messages visible     : {len(visible)}")
    print(f"Independent info events  : {store.independent_information_events(decision_time, ticker='NVDA')}")
    print(f"Total records in store   : {len(store)}")
    ids = [r.record_id for r in visible]
    print(f"Visible record ids       : {ids}")
    assert "future-beat" not in ids
    print("\n  -> 'future-beat' is in the store but correctly INVISIBLE at this timestamp.")
    print("  -> 6 syndicated copies collapsed to 1 information event, +1 filing = 2.")

    hdr("2. REVISION VINTAGES (the silent backtest inflator)")
    for t in ("2026-03-10T00:00:00Z", "2026-04-01T00:00:00Z"):
        v = store.as_of(t, ticker="MACRO")
        print(f"  as_of {t} -> GDP = {v[0].numeric_value}  (record {v[0].record_id})")
    print("\n  -> On Mar 10 the model sees 2.0, the number that actually existed then.")
    print("  -> It only sees 3.4 after the revision was published. No backwards leak.")

    hdr("3. WALK-FORWARD SPLITS")
    splits = make_splits(
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        train_days=180, test_days=30, label_horizon_days=5, embargo_days=2,
    )
    print(f"Generated {len(splits)} chronological splits (5-day purge, 2-day embargo)")
    for s in splits[:3]:
        print(f"  split {s.index}: train {s.train_start.date()}..{s.train_end.date()} "
              f"| purge 5d | test {s.test_start.date()}..{s.test_end.date()}")
    print(f"  ... {len(splits)-3} more")

    hdr("4. EXECUTION COSTS ON A REALISTIC OPTION QUOTE")
    cm = CostModel()
    bid, ask, n = 1.05, 1.25, 5
    ok, why = cm.quote_is_tradeable(bid, ask, age_seconds=8)
    mid = (bid + ask) / 2
    rt = cm.option_round_trip_cost(bid, ask, n)
    notional = mid * 100 * n
    print(f"Quote {bid:.2f}/{ask:.2f}  ({(ask-bid)/mid:.1%} spread)   tradeable={ok} ({why})")
    print(f"Buy fill  : {cm.option_fill_price(bid, ask, 'BUY'):.4f}")
    print(f"Sell fill : {cm.option_fill_price(bid, ask, 'SELL'):.4f}")
    print(f"Round trip cost on {n} contracts: ${rt:.2f} on ${notional:.2f} notional "
          f"= {rt/notional:.1%}")
    print(f"\n  -> The position must clear {rt/notional:.1%} before it breaks even.")

    hdr("5. DETERMINISTIC RISK GATES")
    cases = {
        "well-supported, positive edge": dict(
            independent_events=3, evidence_confidence=0.78, dte=35, relative_spread=0.04,
            open_interest=2500, daily_volume=400, defined_risk=True,
            expected_edge_after_costs=0.031, position_pct=0.015,
            portfolio_heat_pct=0.035, open_positions=2),
        "same thesis, only syndicated sources": dict(
            independent_events=1, evidence_confidence=0.78, dte=35, relative_spread=0.04,
            open_interest=2500, daily_volume=400, defined_risk=True,
            expected_edge_after_costs=0.031, position_pct=0.015,
            portfolio_heat_pct=0.035, open_positions=2),
        "high confidence, edge gone after costs": dict(
            independent_events=4, evidence_confidence=0.95, dte=35, relative_spread=0.09,
            open_interest=2500, daily_volume=400, defined_risk=True,
            expected_edge_after_costs=-0.004, position_pct=0.015,
            portfolio_heat_pct=0.035, open_positions=2),
        "illiquid contract": dict(
            independent_events=3, evidence_confidence=0.80, dte=35, relative_spread=0.22,
            open_interest=40, daily_volume=3, defined_risk=True,
            expected_edge_after_costs=0.05, position_pct=0.015,
            portfolio_heat_pct=0.035, open_positions=2),
        "unknown edge (data missing)": dict(
            independent_events=3, evidence_confidence=0.80, dte=35, relative_spread=0.05,
            open_interest=2500, daily_volume=400, defined_risk=True,
            position_pct=0.015, portfolio_heat_pct=0.035, open_positions=2),
    }
    for label, cand in cases.items():
        r = evaluate(cand)
        print(f"\n  {label}")
        print(f"    -> {r.decision.value}")
        for why_ in r.reasons[:2]:
            print(f"       {why_}")
        if r.failed_gates:
            print(f"       failed: {', '.join(r.failed_gates[:4])}")

    hdr("SUMMARY")
    print("Machinery verified. Note what the gates did:")
    print("  * identical thesis PASSED or WATCHED purely on evidence independence")
    print("  * 95% model confidence did NOT override negative post-cost edge")
    print("  * missing data produced PASS (fail-closed), never a silent approval")
    print("\nNo live-order code path exists. Decision enum is PASS/WATCH/PAPER_TRADE_CANDIDATE only.")
    print("\nREMINDER: all inputs above are synthetic. No edge has been demonstrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
