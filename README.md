# Money Printer

An AI-agent-coordinated market-intelligence and options-research project. Built by a human (Tyler) directing a small team of AI agents — Claude, ChatGPT/Codex, and several Slack-based specialists.

**Paper/simulation only.** No live trading, no broker execution, no moving money, anywhere in this repository. There is no code path anywhere in this codebase that emits a live order.

## Status

76 tests passing in `claude/app/mp_v01/`. Zero external dependencies on Linux/macOS; on Windows, `pip install tzdata` is needed once.

**NEW**: Market Intelligence Engine (DEVELOPMENT ONLY — see CODE_REVIEW_2026-08-13.md)

## Why this exists

The goal is to find out, honestly, whether a small, disciplined, point-in-time-correct research pipeline can identify a real statistical edge in equities/options — and to do it in a way that's statistically sound enough to justify real capital.

## Hard constraints

- Paper/simulation only. No live orders, no broker execution, no moving money.
- No fabricated facts, prices, or citations. Unknown values are marked `UNKNOWN`, never guessed.
- Code is never claimed to work without actually being run.
- Abstention (`PASS`) is the default and preferred outcome over a confident guess.
- Credentials live in environment variables only — never in files, logs, or chat.

## Layout

```
├── market_intelligence_engine.py  DEVELOPMENT ONLY. See CODE_REVIEW_2026-08-13.md
├── requirements.txt               Python dependencies
├── gui.py                         Desktop GUI - run tests, fetch data, browse results
├── CODE_REVIEW_2026-08-13.md      Complete accounting of MIE issues and remediation
├── claude/                        Claude's work: architecture, orchestration, review
│   ├── app/mp_v01/                The core codebase (PRODUCTION STANDARD)
│   ├── market_research/           Data source licensing analysis
│   ├── reports/                   Architecture blueprints, agent design docs
│   └── scheduled_state/           STATE.md — single source of truth
├── codex/                         Codex's workspace (local execution, ingestion)
└── shared/                        Cross-agent data handoffs
```

---

## ⚠️ Market Intelligence Engine — DEVELOPMENT ONLY

**DO NOT USE FOR REAL TRADING.**

The Market Intelligence Engine (`market_intelligence_engine.py`) is a feature scratchpad. See `CODE_REVIEW_2026-08-13.md` for the complete list of blocking correctness issues.

### What's broken:

| Issue | Impact | Status |
|-------|--------|--------|
| Point-in-time correctness | Uses `iloc[-1]` as if available now. No PIT enforcement. | CRITICAL |
| News source | **100% synthetic**. Sentiment weight set to **0**. | CRITICAL |
| `fillna(0)` | Replaces missing SMA (dollar prices) with 0. Model sees stock as $0. | BLOCKING |
| Label definition | Raw 2% threshold, not excess return vs SPY. | BLOCKING |
| Execution costs | Not modeled. Options spreads can cost 10%+ round-trip. | BLOCKING |
| Validation | Zero tests, zero noise floor, zero permutation test. | BLOCKING |
| Train/test split | All data in training set, none held out. No holdout set. | BLOCKING |
| Auto-adjust | Now explicitly `auto_adjust=False` (FIXED). | ✅ FIXED |
| SELL signal | Removed; binary label doesn't support downside forecast. | ✅ FIXED |

### What will be done:

The indicator math will be **harvested and integrated** into `claude/app/mp_v01/src/features/` where it will inherit:
- Point-in-time correctness via `as_of()` API
- Immutable timestamped data store (not overwriting CSVs)
- Deterministic risk gates that fail closed
- Validation via permutation test and noise floor check
- Real data with publication lag modeling

### For now:

**Use `claude/app/mp_v01/run_all.py` for any real evaluation.**

---

## The Production Codebase: `claude/app/mp_v01/`

A point-in-time-correct research pipeline, built to make hindsight structurally impossible rather than merely discouraged.

### Key guarantees:

| Module | What it guarantees |
|--------|-------------------|
| `pit/schema.py`, `pit/store.py` | Every record carries four timestamps. Only `available_time` is ever filterable. Revisions don't leak backwards. Syndicated copies collapse to one info event. |
| `labels/contract.py` | Label = binary sign of 5-trading-day forward log excess total return vs. SPY. Decision clock (15:45 ET) precedes the close it's scored against. Fails closed on unknown data. |
| `backtest/costs.py` | Spread/slippage/fee modeling; stale and wide quotes are rejected, not used. |
| `backtest/walkforward.py` | Chronological train/test splits with purge gap tied to label horizon, plus embargo. |
| `backtest/evaluate.py` | Noise floor via permutation test — distinguishes real edge from chance. Validated to read `NO_EDGE` on pure random data. |
| `gates/risk.py` | Deterministic `PASS` / `WATCH` / `PAPER_TRADE_CANDIDATE` decision gate, outside model judgment. Unknown/invalid inputs fail closed. |
| `adapters/yahoo_daily.py` | Free daily equity bars with realistic publication lag. |
| `adapters/eodhd_options.py` | Paid options chain adapter; token read from env only. |

### Running the production system:

**GUI** (from repo root):
```bash
python gui.py               # run tests, fetch data, browse results
```

**Command line**:
```bash
cd claude/app/mp_v01
python run_all.py          # full zero-dependency test suite (76 tests)

pip install yfinance
python fetch_data.py --tickers SPY,QQQ,MSFT --chains
```

### Test results (76 passing):

```
NO-LOOKAHEAD / POINT-IN-TIME CORRECTNESS
  ✓ future_records_are_invisible
  ✓ boundary_is_inclusive_and_exact_to_the_second
  ✓ publication_lag_is_respected
  ✓ revision_does_not_leak_backwards
  ... (14 passed)

BACKTEST / COSTS / RISK GATES
  ✓ splits_are_chronological_and_non_overlapping
  ✓ overlapping_train_test_rejected
  ✓ future_features_rejected
  ✓ option_buy_pays_up_and_sell_receives_less
  ✓ round_trip_cost_is_material_on_wide_spreads
  ✓ negative_edge_after_costs_is_hard_fail
  ✓ confidence_cannot_override_a_hard_gate
  ... (24 passed)

NOISE FLOOR CHECK
  ✓ Strategy on pure random data: NO_EDGE (correct null)
```

---

## Project Organization

- **Claude** — architecture, orchestration, adversarial code review, QC
- **Codex** — local execution, data ingestion, build
- **Specialist Personas** — domain analysis (sector intelligence, options research, bear-case evidence)

Deterministic risk gates sit outside every model's judgment. A model may only *propose*; `gates/risk.py` *decides*.

See `claude/scheduled_state/STATE.md` for current work list and decision log.

---

## Development Roadmap (from CODE_REVIEW_2026-08-13.md)

### Phase 1 — Ingest for real
Run `fetch_data.py` on real SPY/QQQ/MSFT over the longest free history. Build the JSON→PIT loader.
**Exit:** records in store, `as_of()` returns sane counts, no `UNKNOWN` above threshold.

### Phase 2 — Fix blocking bugs
Purge in bar-index space, block permutation, refit-under-permutation, leak guard wired into eval path.
**Exit:** planted-leak test fires, noise floor still reads `NO_EDGE`.

### Phase 3 — Null run on real bars
Run deliberately worthless strategy (coin flip, always-long, trailing momentum) on real data.
**Exit:** `NO_EDGE`. If a coin flip shows edge, harness is still broken.

### Phase 4 — Component rank IC
Compute walk-forward rank information coefficient of each score component vs forward excess return.
**Exit:** a number for each component. Most likely all near zero (honest result, saves money).

### Phase 5 — Post-cost gate
Feed any surviving signal through `costs.py` and `gates/risk.py`.
**Exit:** `expected_edge_after_costs` figure. If negative (base rate), stop.

### Phase 6 — Forward paper log
Scheduled runs producing frozen, hashed predictions; separate resolver scoring after 5 days.
**Exit:** this is the only genuinely out-of-sample evidence. Worth more than all backtests combined.

---

## Pre-registration (must be decided before seeing results)

Write these numbers down **now** and put in STATE.md:

- **Minimum forward paper predictions before real capital:** ≥ 200 non-overlapping decisions (~4 years weekly on 3 tickers)
- **Required post-cost expectancy:** stated as a number
- **Required calibration:** predicted 70% buckets must resolve within stated band of 70%
- **Maximum acceptable paper drawdown:** stated value
- **Strategy lock:** any change resets the clock. No exceptions, no "small tweaks."
- **Failure condition:** what result makes you abandon the project? (Must exist, or project can't fail/succeed.)

---

## Disclaimer

**This tool is for educational and research purposes only.**

- Not financial advice
- Always conduct due diligence before investing
- Past performance ≠ future results
- Paper trading results do not guarantee live performance
- No live order code path exists anywhere in this repository

---

**Last Updated**: August 13, 2026  
**Version**: 2.1.0 (Market Intelligence Engine marked DEVELOPMENT ONLY, critical fixes applied)
