# Money Printer

An AI-agent-coordinated market-intelligence and options-research project. Built by a human (Tyler) directing a small team of AI agents — Claude, ChatGPT/Codex, and several Slack-based specialist personas — toward a testable trading edge.

**Paper/simulation only.** No live trading, no broker execution, no moving money, anywhere in this repository. There is no code path anywhere in this codebase that emits a live order — see `gates/risk.py`.

## Status

76 tests passing in `claude/app/mp_v01/`. Zero external dependencies on Linux/macOS; on Windows, `pip install tzdata` is needed once (the timezone-correct date math in `labels/contract.py` and the adapters relies on the IANA tz database, which Windows doesn't ship for Python's `zoneinfo`). No real market data has been ingested yet. No strategy has been evaluated. No edge has been demonstrated. Any claim otherwise, from any agent, should be treated as false until it's backed by a run against real (not synthetic) data.

## Why this exists

The goal is to find out, honestly, whether a small, disciplined, point-in-time-correct research pipeline can identify a real statistical edge in equities/options — and to do it in a way that's structurally incapable of fooling itself with lookahead, survivorship bias, or silent data revision. If it can't, the pipeline is designed to say so (`NO_EDGE`) rather than manufacture a result.

## Hard constraints

- Paper/simulation only. No live orders, no broker execution, no moving money.
- No fabricated facts, prices, or citations. Unknown values are marked `UNKNOWN`, never guessed.
- Code is never claimed to work without actually being run.
- Abstention (`PASS`) is the default and preferred outcome over a confident guess.
- Credentials live in environment variables only — never in files, logs, or chat. See `claude/reports/CREDENTIAL_SETUP.md`.

## Layout

```
├── gui.py                   Desktop GUI - run tests, fetch data, browse results. Start here.
├── claude/                  Claude's work: architecture, orchestration, adversarial review, QC
│   ├── app/mp_v01/          The codebase — see below
│   ├── market_research/     Data source and provider licensing analysis
│   ├── reports/             Architecture blueprints, agent design docs, tiering notes
│   └── scheduled_state/     STATE.md — single source of truth for cold/scheduled sessions
├── codex/                   Codex's workspace (local execution, ingestion, build)
└── shared/                  Cross-agent data handoffs (e.g. shared/data/bars/)
```

## The codebase: `claude/app/mp_v01/`

A point-in-time-correct research pipeline, built to make hindsight structurally impossible rather than merely discouraged.

| Module | What it guarantees |
|---|---|
| `pit/schema.py`, `pit/store.py` | Every record carries four timestamps (event/published/available/ingested). Only `available_time` is ever filterable. Revisions don't leak backwards. Syndicated sources collapse to one information event. |
| `labels/contract.py` | Label = binary sign of 5-trading-day forward log excess total return vs. SPY. Decision clock (15:45 ET) precedes the close it's scored against by design. Fails closed on unresolved corporate actions. |
| `backtest/costs.py` | Spread/slippage/fee modeling; stale and wide quotes are rejected, not used. |
| `backtest/walkforward.py` | Chronological train/test splits with a purge gap tied to the label horizon, plus embargo. |
| `backtest/evaluate.py` | Noise floor via permutation test — the mechanism that tells the difference between a real edge and chance. Validated to read `NO_EDGE` on pure random data. |
| `gates/risk.py` | Deterministic `PASS` / `WATCH` / `PAPER_TRADE_CANDIDATE` decision gate, outside all model judgment. Unknown or invalid (NaN/Inf) inputs fail closed, never silently pass. No live-order path exists. |
| `gates/account_profiles.py` | Small-account ($1,000) position-sizing math — standard 2%/6% limits are arithmetically infeasible at that size. |
| `adapters/yahoo_daily.py` | Free daily equity bars. A bar is not "available" at its own close — encodes realistic publication lag so predictions can't see the price they're scored on. |
| `adapters/eodhd_options.py` | Paid options chain adapter. Token read from `EODHD_API_TOKEN` only; scrubbed from any logged text. |
| `fetch_data.py` | Runnable CLI to pull real data: `python fetch_data.py --tickers SPY,QQQ,MSFT --chains` |

### Quickstart

GUI (from the repo root):
```bash
python gui.py               # run tests, fetch data, and browse results from one window
```

Command line:
```bash
cd claude/app/mp_v01
python run_all.py          # runs the full zero-dependency test suite

pip install yfinance
python fetch_data.py --tickers SPY,QQQ,MSFT --chains   # pulls real market data
```

## How this project is run

- **Claude** — architecture, orchestration, adversarial code review, quality control.
- **Codex** — local execution, data ingestion, build work.
- **ChatGPT-based Slack personas** — domain analysis (sector intelligence, options research, bear-case evidence audits, test reproducibility, etc.), each constrained to structured, fail-closed JSON output.

Deterministic risk gates sit outside every model's judgment. A model may only ever *propose*; `gates/risk.py` *decides*, and `PAPER_TRADE_CANDIDATE` is a nomination for simulation, never an authorization to trade.

See `claude/scheduled_state/STATE.md` for the current open-work list and decision log.
