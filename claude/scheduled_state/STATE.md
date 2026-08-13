# Money Printer — STATE (single source of truth for cold sessions)

**Read ONLY this file to resume. Do not read the other docs unless you need a specific detail.**
They exist for Tyler, not for you. Reading all of them costs ~5x this file for no added capability.

**THIS FILE LIVES AT:** `C:\Users\Tyler\Documents\MoneyPrinter\claude\scheduled_state\STATE.md`
**PROJECT ROOT:** `C:\Users\Tyler\Documents\MoneyPrinter\` — connected as a persistent Cowork folder as of 2026-08-13 ~08:35 CDT. If you are a cold scheduled-task session and this path is not accessible to you, STOP and report that explicitly rather than treating the project as brand new — a prior 7-run failure (1-7 AM, 2026-08-13) did exactly that because no folder was connected yet. That bug is fixed now; if you still can't reach this path, it's a new problem worth surfacing, not a green light to start from scratch.

Layout:
- `claude/app/mp_v01/` — the codebase. `python run_all.py` from here.
- `claude/market_research/` — data source and provider analysis
- `claude/reports/` — architecture blueprints, agent design, tiering docs
- `claude/scheduled_state/STATE.md` — this file
- `claude/MORNING_ACTIONS.md`, `claude/START_HERE_MORNING_QC.md` — Tyler-facing, at the top level
- `codex/` — reserved for Codex's work, once Tyler points it here. Do not write here.
- `shared/` — cross-agent handoffs, once both sides use this folder. Currently empty; Slack is still the handoff channel until Codex is confirmed writing here too.

Last updated: 2026-08-13 ~08:52 CDT

---

## Approved decisions — settled, do not re-litigate

- **Universe:** SPY, QQQ, MSFT (`INDEX_PLUS_ONE`). Supersedes semiconductor-first.
- **Label contract v1.0** (implemented + tested): binary sign of 5-trading-day forward log excess total return vs SPY, close-to-close, decision clock 15:45 ET, label starts at the t close.
- **Reproducibility:** RFC 8785 canonical JSON + SHA-256, append-only frozen predictions, float tolerance `1e-12 + 1e-9*max(|a|,|b|)`, differing env fingerprint → UNTESTED.
- **Data:** Yahoo/yfinance (free) for equity bars — decades of history, no meaningful cap. EODHD paid tier only after a stock-level edge exists. EODHD **free** tier is unusable (20 calls/day, 1yr history, options cost 10 calls each). CRSP deferred.
- **Capital:** $1,000 eventually, after beta + extensive simulation. Standard 2%/6% limits are arithmetically infeasible at $1,000 (one contract ≈ 11.5% of account) — see `src/gates/account_profiles.py`.
- **Structures:** no a priori preference; post-cost expectancy decides.
- **Roles:** Claude = architect, orchestration, adversarial review, Q/C. Codex = local execution, ingestion, build. ChatGPT personas = domain analysis.

## Hard constraints

Paper/simulation only. No live orders, no broker execution, no moving money. No fabricated facts, prices, or citations — mark unknowns UNKNOWN. Never claim code works without running it. Abstention (PASS) is preferred. Credentials live in env vars only, never in files/logs/chat.

---

## Built and passing: 76 tests, zero dependencies on Linux/macOS (Windows needs `pip install tzdata`, see below)

`mp_v01/` — run `python run_all.py`.

| Module | What it guarantees |
|---|---|
| `pit/schema.py`, `pit/store.py` | Four-timestamp contract; only `available_time` filterable; revision vintages don't leak backwards; syndication collapses to one event; unknown lineage = zero corroboration |
| `labels/contract.py` | Label v1.0; decision clock precedes the close it's scored against; fails closed on unresolved corporate actions |
| `backtest/costs.py` | Spread/slippage/fees; stale + wide quote rejection. Realistic option round trip ≈ **10.1% of notional** |
| `backtest/walkforward.py` | Chronological splits, purge tied to label horizon, embargo |
| `backtest/evaluate.py` | **Noise floor via permutation test.** Validated: reads NO_EDGE on random data, SIGNAL_CANDIDATE on planted leak |
| `gates/risk.py` | Deterministic PASS / WATCH / PAPER_TRADE_CANDIDATE. No live path exists. Confidence cannot override negative post-cost edge |
| `gates/account_profiles.py` | Small-account feasibility math |
| `common/timezones.py` | Shared IANA tz (`America/New_York`) — replaces a hard-coded UTC-4 offset that was silently wrong for ~5 months/year (standard time). Windows needs `pip install tzdata`; raises a clear error if missing rather than a wrong answer. |
| `adapters/yahoo_daily.py` | Free bars; bar NOT available at its own close; gaps break the chain, never bridged |
| `adapters/eodhd_options.py` | Paid chains; token from `EODHD_API_TOKEN`; `redact()` scrubs it from any log text |
| `fetch_data.py` | Runnable fetcher. `python fetch_data.py --chains` |

**Not built:** real data ingested, any strategy, any backtest result, any alpha.

---

## Open work, in priority order

1. **Run `fetch_data.py` against real Yahoo data** (needs Tyler's machine — no network in Claude's sandbox)
2. **Baseline evaluation on real bars** — establish the noise floor on actual SPY/QQQ/MSFT, not synthetic
3. **D — option valuation/exit contract** (unanswered 4 rounds): joint spot/IV path model, profit target / stop / DTE time stop, early assignment + ex-dividend, liquidity screen
4. **F — audit packet** (unanswered 4 rounds): canonical hashing, round-1 blinding, claim-to-evidence matrix
5. 4-way train/tune/calibration/test split with exactly-once final evaluation
6. DISPUTED lineage state machine (spec exists; only simplified UNKNOWN sentinel implemented)

## Known operational facts

- Slack `#all-money-printer` = `C0BPQDPJKHR`. Mention **all seven** subteam tags or routing fails. Specialists see **thread context only** — inline anything under review.
- **Specialists rate-limit after ~4 rounds.** If two consecutive rounds get no reply, stop posting and do the work directly.
- `options_research` and `bear_audit` have been silent 3+ rounds.
- Codex owns `outputs/codex_alpha/` — never write there. Codex hit its usage limit 2026-08-13.
- Ignore the stale `money_printer/` folder.

---

## Run log

(Cold sessions: append a short entry here after each run. Timestamp, one line on what you did, real test count, anything Tyler must decide. Keep entries to 2-4 lines each.)

- **2026-08-13 ~08:52 CDT** — Posted CODE-REVIEW-001/DATA-REQUEST-001, got real specialist responses. Fixed a genuine bug `00-Money Printer` (ChatGPT's orchestrator persona) found in `gates/risk.py`: NaN/Inf inputs bypassed threshold comparisons silently (NaN comparisons are always False) instead of failing closed — could have let a malformed candidate reach PAPER_TRADE_CANDIDATE. Added `_bad_numeric()` guard + 5 tests. GitHub repo confirmed **private, empty (README only)** at the time — and confirmed via Slack that ChatGPT's own runtime also has no outbound GitHub access (403 on `git ls-remote`), same as my sandbox. **Decision: GitHub deferred at that point, local `shared/` folder primary handoff.** Data fetch confirmed-blocked from 3 independent runtimes — only Tyler running `fetch_data.py` locally unblocks this (still true). Flagged to Tyler: `00-Money Printer` posted a separate, heavier Version-0.1 blueprint (Postgres/API/worker services), parallel/competing with `mp_v01` — did not approve it, surfaced to Tyler instead.
- **2026-08-13 ~09:15 CDT** — Tyler created a real local git repo (`MoneyPrinter/MoneyPrinter/`) and asked me to populate + commit it for publishing. Copied `claude/`, `codex/`, `shared/` in, added `.gitignore`, wrote a real README, verified no secrets in the diff, committed (81 tests at that point), confirmed with Tyler it's live and public at `github.com/tylerj-spec/MoneyPrinter`. Note: Cowork's connected-folder mount blocks file deletion by default, which breaks git's lock-file mechanics — had to request delete permission once via `allow_cowork_file_delete` to clear a stray `index.lock`. Resolved; git now works normally in that folder from this sandbox.
- **2026-08-13 ~09:40 CDT** — Tyler pasted a code review from GitHub Copilot. Verified each claim independently rather than applying blindly. Confirmed real: hard-coded `ET_UTC_OFFSET_HOURS = 4` in three files was silently wrong ~5 months/year (only valid during EDT; breaks during EST, Nov–Mar). Proved it concretely: `decision_time_utc_for("2026-03-05")` returned 19:45 UTC before the fix; correct answer is 20:45 UTC since 2026 DST doesn't start until Mar 8. Fixed via new shared `src/common/timezones.py` (zoneinfo/IANA tz db, graceful error if `tzdata` missing on Windows) — replaces the offset in `yahoo_daily.py`, `labels/contract.py`, `eodhd_options.py`. Also fixed: `normalize_bars` NaN check now type-agnostic (was `isinstance(close, float)`, missed non-float-subclass NaN types); `build_label` now catches `ValueError` from `log_total_return` and returns a new `RETURN_GAP_UNRESOLVED` status instead of crashing on a gap day inside an otherwise-sufficient window. Added `requirements.txt` (optional, live-fetch only) and `.github/workflows/tests.yml` (CI runs `run_all.py` stdlib-only on ubuntu-latest, Python 3.10–3.12). **76 tests passing** (corrected count — earlier "81" figure was a miscount, apologies for the confusion). Pushed back on a few Copilot suggestions as already-correct or intentional: exact-zero edge already fails (`edge <= 0`), `log(0)=-inf` already handled deliberately, "UNKNOWN" vs "NO_PRIOR_CLOSE" status naming is intentional (different semantic meanings, not an inconsistency). **Left uncommitted per Tyler's request** — he wants to review the diff himself before committing.

---

## Token discipline for scheduled runs

Session limit binds before weekly. A cold start re-deriving context is the main cost.

**Do:** read this file only. Run `run_all.py` once, not per-change. Do one focused thing per run and write it down.
**Don't:** re-read all project docs, re-run the suite repeatedly, or post more than one Slack round per run.
**If you can only do one thing:** advance item 1 or 2 above. They unblock everything else.
