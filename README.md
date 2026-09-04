# Money Printer

An AI-agent-coordinated market-intelligence and options-research project. Built by a human (Tyler) directing a small team of AI agents — Claude, ChatGPT/Codex, and several Slack-based specialists.

**Paper/simulation only.** No live trading, no broker execution, no moving money, anywhere in this repository. There is no code path anywhere in this codebase that emits a live order.

## Status

163 tests passing (Run → Run the test suite, or `python run_tests.py`): 131 in `claude/app/mp_v01/`, 32 covering the Excel export and GUI. CI runs on Linux **and Windows**. Zero external dependencies on Linux/macOS; on Windows, `pip install tzdata` is needed once.

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
├── generate_picks.py              Frozen, hashed paper picks from the PIT store
├── resolve_picks.py               Scores an earlier pick file against what happened
├── picks/                         The forward paper record - COMMIT THESE
├── run_gui.bat                    Windows double-click launcher for the GUI
├── diagnose.py                    Setup report - what this copy is and what it produced
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

### Running it

Everything is a button. There are no commands to type.

**Windows:** double-click `run_gui.bat`.
**macOS / Linux:** `python gui.py`.

First time only, inside the app: **Install required packages**, then **Check setup**.
That installs `yfinance`, `openpyxl` and `tzdata` into the right interpreter and
confirms the install worked. If anything ever looks wrong, **Check setup** is the
first thing to press — it reports which commit you are on, what data you have, and
whether a workbook was built by older code.

### What the buttons do

| Button | What it does |
|---|---|
| **Install required packages** | Installs the three packages a first run needs, into the interpreter the app is running on. Safe to repeat. |
| **Check setup** | Read-only report: commit, features present, data store contents, pick files, and whether any workbook is stale. |
| **1 · Fetch market data** | Downloads daily bars from Yahoo. Every run writes a new immutable file and overwrites nothing. |
| **2 · Build Excel workbook** | Turns the data store into a workbook — bars, labels, option chain with Greeks, and the accumulated pick history. |
| **3 · Generate paper picks** | Scores every ticker under five weight variants, proposes a contract for each, freezes the result with a SHA-256, and rebuilds the workbook. |
| **4 · Score past picks** | Takes the newest frozen file and works out what happened: was the direction right, and what would the pre-registered exits have returned. |
| **Open output folder** | Opens where the workbooks are, with the newest selected. |

Tick **"also snapshot option chains"** before fetching if you want Greeks or picks.
Yahoo publishes no historical chains, so a daily snapshot is the only way to build
options history — and without a chain there is nothing to compute Greeks from or
choose a contract out of.

### In the menu

| Menu item | |
|---|---|
| File → Open the picks folder | The forward record. Commit this folder — unlike the data store it cannot be regenerated. |
| Run → Score a specific pick file… | Score an older file rather than the newest. |
| Run → Run the test suite | 161 tests, no network, no market data. |
| Run → Market Intelligence Engine | Development only. Unvalidated, not point-in-time correct, synthetic news input. |
| Help → What each button does | The same reference, inside the app. |

### If you prefer a terminal

Every button just runs a script, and the exact command is echoed in the console:

```bash
python run_tests.py                                  # the full suite
python diagnose.py                                   # the setup report
python claude/app/mp_v01/fetch_data.py --chains      # fetch
python excel_report.py                               # build the workbook
python generate_picks.py                             # freeze picks
python resolve_picks.py picks/<file>.json            # score them
```

---

## Paper picks — the forward record

The roadmap's Phase 6, and the only genuinely out-of-sample evidence this project
will produce. Requires a fetch **with chains**:

```bash
python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT --chains
python generate_picks.py
```

Five weight variants run against the same snapshot — `momentum`, `trend_quality`,
`reversion`, `balanced`, `equal_weight_control`. `reversion` deliberately
contradicts the momentum variants: **if both look good in the forward record, the
record is noise rather than two edges.** Every variant is logged on every run,
including the ones that look bad. Quietly dropping a variant that underperformed
turns the whole record into a selection artefact.

Each proposal carries the contract, the Greeks, execution cost, the breakeven move
needed just to cover costs, the risk gate's verdict, and a paragraph of rationale
built from the numbers actually used. Abstentions are recorded with their reason,
never dropped — "the strategy proposed nothing" and "the data was unusable" are
different statements.

### Exit rules are pre-registered

Written into the file at generation time, before any outcome is known:

| | |
|---|---|
| **Primary** | Mark to market after **5 trading days** and score the directional call. Matches the label contract horizon, so paper results stay comparable with what the model is scored against. |
| **Secondary** | Close at **+50% / −50%** of premium. Path-dependent, recorded separately — a different question from whether the call was right. |
| **Hard exit** | Close below **21 DTE**, whatever the P&L. Theta and gamma both accelerate there and the contract stops behaving like the one that was chosen. |

Deciding when to close *after* watching the position is how a loser becomes "still
developing." Changing these mid-flight invalidates the record.

### The history accumulates in Excel

`Pick_History` is a **view over every frozen file in `picks/`**, not something the
workbook remembers. So rebuilding the workbook never loses history, and committing
`picks/` is what preserves it. Regenerate any time:

```bash
python excel_report.py          # rebuilds every sheet, history included
```

Or click **3 · Generate paper picks** in the GUI, which freezes today's run and then
rebuilds the workbook so the new picks appear alongside every earlier one.

Each row carries the outcome and **which pre-registered rule closed the position** —
found by walking the path day by day, not by checking only the horizon:

| `exit_trigger` | Meaning |
|---|---|
| `PROFIT_TARGET` | Return on premium reached +50% |
| `STOP_LOSS` | Return on premium reached −50% |
| `DTE_FLOOR` | Days-to-expiry fell below 21 |
| `TIME_STOP` | None of the above fired before the 5-day horizon |

Checking only the horizon would convert every stop-out into a round trip — reporting
losses a disciplined trader would never have taken, and worse, reporting gains on
positions already stopped out.

Two column families, deliberately never merged:

- **`exit_*`** — what following the rules would have returned. Path dependent.
- **`horizon_*`** — whether the directional call was right, measured at the label
  horizon regardless of how the position closed. This is what the label contract
  scores. A stop-out does not erase the directional answer.

`integrity` reads `VOID` if a file's picks no longer hash to their recorded digest.
Those rows are still shown, but excluded from `Pick_Performance`.

### Scoring it later

```bash
python resolve_picks.py picks/picks_2026-09-03_20260903-160000.json
```

The resolver re-hashes the picks before doing anything else. A mismatch means the
file was edited after generation and it refuses to score — that check is the whole
reason a forward log beats a backtest.

Marks are **MARKET** where a later chain snapshot contains the exact contract, and
**MODELLED** otherwise (Black-Scholes at the later close, assuming IV unchanged —
the assumption most likely to be wrong after a real move). The two are reported
separately and never mixed. Fetch daily with `--chains` and you get market marks.

**None of this is gate-approved.** `gate_decision` reads `PASS` — do nothing — on
every pick, because a chain snapshot plus an unvalidated component score contains
no independent evidence count and no measured post-cost edge, and the gate fails
closed on what it is not told. That is the loop working: the forward record is what
will eventually *produce* the edge estimate the gate needs. The pre-registration
above asks for **≥200 non-overlapping decisions** before any of it means anything.

---

## Installation

1. **Python 3.10 or newer.** On Windows install from python.org with
   **"Add python.exe to PATH"** ticked. Verified working on 3.10 through 3.14.
2. **Clone or download this repository.**
3. **Start the app** — `run_gui.bat` on Windows, `python gui.py` elsewhere.
4. **Press "Install required packages"** inside the app.

That is the whole setup. The three packages it installs:

| | |
|---|---|
| `yfinance` | fetches the market data |
| `openpyxl` | writes the Excel workbooks |
| `tzdata` | the IANA timezone database. **Not optional on Windows** — Windows ships no such database, so `zoneinfo` cannot resolve `America/New_York` and the label contract's 15:45 ET decision clock cannot be built at all. |

The heavy pins in `requirements.txt` — pandas, scikit-learn, backtrader — are only
for the development-only Market Intelligence Engine. The main app does not need them.

**If the app will not start:** Python is probably not on PATH. On Windows, if typing
`python` opens the Microsoft Store, use the `py` launcher instead, or reinstall with
the PATH box ticked.

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
**Version**: 2.8.0 (Every step behind a button, Windows CI, 163 tests)
