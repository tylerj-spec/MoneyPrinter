# Money Printer — Version 0.1 Architecture Blueprint

Status: DRAFT, pending Tyler's approval. Architecture mode only — no implementation started against this doc yet.

This synthesizes the authoritative Instructions/Handoff, the six specialist personas' outputs so far (via the single ChatGPT Agents app in Slack), and the direct Slack transcript from `#all-money-printer` and `#market-ai-orchestration` on 2026-08-12.

## 1. What this system is (and isn't)

A local-first, auditable market-intelligence and options-research platform that scores whether a directional stock thesis is supported by point-in-time evidence, then separately scores whether any specific option structure is worth taking. It outputs one of three states — `PASS`, `WATCH`, `PAPER_TRADE` — never a live order. Live execution stays disabled until Tyler explicitly turns it on after backtest + paper-trading validation.

It is not: a live-trading bot, a system that invents data when sources are missing, or a place where confidence overrides hard-coded risk limits.

## 2. Highest-risk assumption (flagging early, per your own instruction)

**Historical options data quality/availability.** All three specialist reviews independently converged on the same conclusion: getting sufficiently accurate, legally licensed historical options quotes (bid/ask, Greeks, IV surface) for honest backtesting is the biggest open risk. Free sources are typically EOD-only or missing intraday spreads/Greeks; realistic backtesting needs point-in-time quotes including stale/wide-quote conditions. This should be validated — with a real vendor quote or free-tier sample — before any options-layer code is written, not after.

Secondary risk: the Slack multi-agent setup is currently one bot app switching display names (see §6), not independently operating agents, which affects how much "independent first-round blind analysis" is actually happening today.

## 3. Pipeline (converged across all three specialist reviews)

```
permitted source → immutable raw data → normalized records → evidence/lineage mapping
→ point-in-time queries → reproducible test manifest
→ [stock-ranking: calibrated return/vol forecast vs. simple baseline, walk-forward, no leakage]
→ [options economics: qualified forecast + timestamped chain + cost/fill model + portfolio limits]
→ [adversarial evidence audit: claim verification, lineage dedup, cutoff violations, contradictions]
→ [deterministic risk gates: hard-coded limits, cannot be overridden by model confidence]
→ decision: PASS | WATCH | PAPER_TRADE
```

Two boundaries every specialist independently insisted on:
- **Thesis vs. contract are scored separately.** A correct directional call doesn't make a specific option attractive — options economics is its own gate (liquidity, spread, theta, IV, defined-risk structure, 21–60 DTE starting point).
- **Analysis vs. authority are separate.** LLMs analyze and propose; deterministic code and calibrated models score and gate. No specialist agent issues a final trade recommendation.

## 4. Specialist roles (as defined so far)

| Role | Responsibility | Explicitly out of scope |
|---|---|---|
| Data/lineage | Point-in-time ingestion, `event_time`/`published_time`/`available_time`/`ingested_time`, immutable raw → normalized records, dedup syndicated sources | Scoring, picks |
| Sector intelligence | Entities, events, bull/bear evidence IDs, contradictions per sector | Final pick |
| Quantitative research | Baselines, walk-forward splits, leakage checks, calibration, regime/cost sensitivity | Contract selection, live execution |
| Options research | Option-chain economics, cost/fill/slippage modeling, structure comparison vs. stock/cash/no-trade | Inventing the stock thesis |
| Adversarial evidence audit | Claim verification against evidence IDs, cutoff-violation checks, alternative explanations | Producing new evidence |
| Test/reproducibility | Manifest hashing, environment lock, dataset/schema versioning | Strategy judgment |
| Money Printer (coordinator) | Reconciles specialist outputs into one project map; does not issue picks itself | Trading decisions |

## 5. Proposed first vertical slice: semiconductor-first V0.1

Rather than building all six layers generically, implement one narrow path end to end first: one data provider, one sector (semiconductors), one simple baseline strategy, through to a `PASS`/`WATCH`/`PAPER_TRADE` output with a full audit trail — before generalizing. This was proposed in an earlier thread but not yet approved; flagging it here for explicit sign-off since it materially shapes what gets built first.

## 6. Slack orchestration — current real state (verified today, not assumed)

- `#all-money-printer` has 3 real members: Tyler, Claude, and a single `ChatGPT Agents` app. `#market-ai-orchestration` has 2: Tyler and `ChatGPT Agents` — Claude is not currently in that channel.
- Every persona reply (00-Money Printer, 03-Quant Research Agent, 04-Bear Evidence Auditor, etc.) comes from the same Slack app/bot ID, just posting under a different display name per message. There is no evidence yet of genuinely separate bot integrations.
- Smoke test result (from the transcript, not a clean `ORCH-SMOKE-00x` run): bot-authored `@mentions` / user-group mentions do **not** trigger other agents' Slack event routes. Only Tyler's human-authored mentions do. So autonomous agent-to-agent delegation "without human relay" — the exact thing your instructions require to be proven before relying on Slack for overnight orchestration — is currently **not working**, by the bot's own diagnosis in-thread.
- Practical implication: either (a) keep a human/Claude-as-API-relay in the loop for now rather than assuming overnight autonomy, or (b) investigate the ChatGPT Agents Slack app's event-subscription config (outside what Slack's user-token API can inspect or change) to see if bot-to-bot events can be enabled.

## 7. Deployment preferences on record

Single minimal Docker Compose stack, local-first on the Windows 11 desktop (Ryzen-class CPU, ~32GB RAM — exact GPU/VRAM/storage/WSL2 status still unverified). Free data and existing subscriptions first; local models for high-volume/cheap extraction, paid cloud models only for hard/high-value cases. No premium hardware purchase until a measured bottleneck justifies it — historical options data quality is the more likely first dollar spent, not a workstation.

## 8. Open decisions needed from Tyler before implementation starts

1. Approve or reject the semiconductor-first vertical slice (§5).
2. Pick the first data provider to validate for historical options quotes (§2) — this blocks honest backtesting either way.
3. Decide how to handle Slack orchestration given §6: keep manual/Claude-relay coordination for now, or hold implementation until agent-to-agent routing is actually fixed and re-tested.
4. Confirm the six specialist roles/boundaries in §4 as-is, or adjust before they're built into code/prompts.

## Decision log
- 2026-08-12: Semiconductor-first V0.1 proposed by a specialist thread, not yet approved.
- 2026-08-12: Informal comm test in `#all-money-printer` showed bot-authored mentions don't route between agents; no formal `ORCH-SMOKE-001`/`002` PASS/FAIL was ever published to the channel despite being requested.
