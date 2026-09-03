# Money Printer

An AI-agent-coordinated market-intelligence and options-research project. Built by a human (Tyler) directing a small team of AI agents — Claude, ChatGPT/Codex, and several Slack-based specialists.

**Paper/simulation only.** No live trading, no broker execution, no moving money, anywhere in this repository. There is no code path anywhere in this codebase that emits a live order.

## Status

132 tests passing (`python run_tests.py`): 102 in `claude/app/mp_v01/`, 30 covering the Excel export and GUI. Zero external dependencies on Linux/macOS; on Windows, `pip install tzdata` is needed once.

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
├── gui.py                         Desktop GUI - fetch data, build the Excel workbook
├── run_gui.bat                    Windows double-click launcher for the GUI
├── excel_report.py                Data store -> .xlsx (bars, labels, summary)
├── run_tests.py                   Runs every suite in the repo
├── tests/                         Tests for the Excel export and the GUI
├── excel_out/                     Generated workbooks (gitignored)
├── CODE_REVIEW_2026-08-13.md      Complete accounting of MIE issues and remediation
├── CODE_REVIEW_2026-09-02.md      Follow-up review; 6 of 11 findings now fixed
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
| `backtest/evaluate.py` | Noise floor via permutation test, with the model **refit under permutation** and the permutation done in **blocks** so overlapping labels keep their autocorrelation. Validated to read `NO_EDGE` on pure random data, including for a genuinely fitted strategy. |
| `gates/risk.py` | Deterministic `PASS` / `WATCH` / `PAPER_TRADE_CANDIDATE` decision gate, outside model judgment. Unknown/invalid inputs fail closed. |
| `adapters/yahoo_daily.py` | Free daily equity bars with realistic publication lag. |
| `adapters/eodhd_options.py` | Paid options chain adapter; token read from env only. |

### Running the production system:

**GUI** (from repo root):
```bash
python gui.py               # or double-click run_gui.bat on Windows
```

Three buttons, in order: fetch data, build the Excel workbook, open the folder.
The test suite and the dev-only MIE sit under Advanced. Every command it runs is
echoed into the console, so anything the GUI does you can also do from a terminal.

**Command line**:
```bash
python run_tests.py        # every suite: pipeline, Excel export, GUI (132 tests)

cd claude/app/mp_v01
python run_all.py          # just the zero-dependency pipeline suite (102 tests)

pip install yfinance
python fetch_data.py --tickers SPY,QQQ,MSFT --chains
```

---

## Working in Excel

`excel_report.py` turns the point-in-time store into one workbook. It imports
`labels/contract.py` rather than re-deriving the target, so the spreadsheet and
the codebase cannot drift apart on what `y` means.

```bash
python excel_report.py                      # everything in the store
python excel_report.py --tickers SPY,MSFT   # a subset
```

| Sheet | What's in it |
|-------|--------------|
| `README` | Generated timestamp, source vintage files, label definition, what every status value means |
| `Summary` | One row per ticker: coverage, gap count, label base rate |
| `Bars_<TICKER>` | OHLCV, dividends, daily total return, both PIT timestamps, plus **live formulas** for `sma_20`, `sma_50`, `vol_20d_annualised` |
| `Labels` | The label contract v1.0 target: 5-day forward log excess total return vs SPY, its sign, and the fail-closed status |
| `Options_Summary` | Per underlying: contracts snapshotted, how many carry a two-sided quote, how many could be modelled, how many survive the liquidity screen |
| `Options_<TICKER>` | One row per contract — quote, solved IV, the five Greeks, execution cost, and the screens. Only present if you fetched with `--chains` |

The SMA and volatility columns are real Excel formulas, not pasted values — widen
the `AVERAGE()` range and the column recalculates, so windows can be retuned in
the sheet without touching Python. All three look backwards only.

Three things worth knowing before you trust a cell:

- **Blank means missing.** Nothing is interpolated or forward-filled. A gap breaks
  the return chain and turns the affected labels `RETURN_GAP_UNRESOLVED`.
- **`available_time_utc` is the only timestamp a backtest may filter on.** It is the
  morning *after* the session, not that session's own close.
- **The `Labels` sheet is the answer key.** Forward-looking by construction: correct
  for fitting and scoring, never as an input feature.
- **SPY must be in the store.** Excess return vs SPY is undefined without it, so no
  labels are built for other tickers and the workbook says so rather than
  substituting a different benchmark.

Each export writes a new timestamped file under `excel_out/`, so a workbook you have
edited by hand is never overwritten.

### Options and the Greeks

Yahoo publishes a two-sided quote, volume, open interest and its own IV figure — **not**
Greeks. So the Greeks are computed, by `src/options/greeks.py` (Black-Scholes, standard
library only, 13 tests against published reference values and put-call parity).

What that means for reading the sheet:

| | |
|---|---|
| **Observed** | bid, ask, strike, expiration, volume, open interest, underlying close |
| **Modelled** | `iv_solved` and every Greek |

- **`iv_solved`, not `iv_yahoo`, drives the Greeks.** Yahoo's IV comes from an undocumented
  model with an undocumented rate and dividend assumption; feeding it into these formulas
  would stack this model on an unknown one. IV is inverted from the observed mid instead, so
  the chain is quote → one documented model → Greeks. Both columns are shown: a wide gap
  between them is a data-quality warning about that contract.
- **The underlying is the prior session's close**, not live spot — a bar is not consumable at
  its own close, and using the snapshot day's own close would be a full day of lookahead in
  every delta. `underlying_close_date` shows which bar was used.
- **`model_status` explains every blank.** No two-sided quote, expired, IV unsolvable from the
  mid. Nothing is ever filled with a plausible substitute.
- **The risk-free rate is an assumption**, not data. Default 4%, override with
  `--risk-free-rate`, and it is printed on the README sheet.
- **`gate_decision` returns `PASS` — meaning do nothing — on every row.** `gates/risk.py` runs
  per contract on what a snapshot actually contains, and a snapshot has no evidence count, no
  confidence, and no post-cost edge. `gate_missing` names exactly what is absent.

**The liquidity screen narrows the chain. It does not make a pick.** Per this project's own
sequencing in `yahoo_daily.py`, an options overlay cannot rescue a stock-level forecast with
no demonstrated edge — and none has been demonstrated yet. See `CODE_REVIEW_2026-09-02.md`
§2.2: the harness that would measure one currently cannot distinguish signal from noise.

---

## Local setup (Windows)

```bat
pip install yfinance openpyxl tzdata
```

That is everything the GUI and the Excel export need — the heavy pins in
`requirements.txt` (pandas, scikit-learn, backtrader) are only for the
development-only Market Intelligence Engine.

Then double-click `run_gui.bat`, or:

```bat
python gui.py
```

If Python is not found, reinstall from python.org with **"Add python.exe to PATH"**
ticked. `tzdata` is required on Windows: `zoneinfo` has no IANA database there, and
the label's 15:45 ET decision clock would otherwise be an hour off for half the year.

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

**Last Updated**: August 29, 2026  
**Version**: 2.5.0 (Permutation null fixed, Options Greeks, Excel export, 132 tests)
