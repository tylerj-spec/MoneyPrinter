# Money Printer — Version 0.2 Blueprint

Supersedes V0.1. Produced 2026-08-12 ~23:25 CDT from SPEC-ROUND-003 with the Slack specialists.
Status: **specification substantially complete for the data/label/reproducibility layers.** Options valuation and audit-packet layers still open.

Everything marked **PROPOSED** is a specialist default awaiting Tyler's accept/reject. Nothing here has been implemented against real data.

---

## 0. Two things that need Tyler's decision before anything else

**0.1 — The first slice vote went against your approval, unanimously.**
Every specialist that voted chose `INDEX_PLUS_ONE` over `SEMIS`. Proposed universe: **SPY + QQQ + MSFT** (MSFT as the predeclared large-cap). The reasoning is consistent across all four: SPY and QQQ act as explicit market and tech-beta controls, so incremental issuer-specific signal can be separated from correlated sector exposure. In a semiconductor-only slice, one macro event moves every name at once and a model can look predictive while tracking nothing but sector beta.

You approved semiconductor-first. I have not overridden that. **This is the one decision that gates everything downstream.**

**0.2 — The proposed spec quietly requires a paid data subscription.**
The label contract leans on **CRSP** (via WRDS) for point-in-time universe membership, corporate actions, delisting returns (`DLRET`), and PERMNO-keyed identity resolution. CRSP is not free — WRDS access is typically an institutional subscription, often five figures annually. That directly conflicts with your stated preference for free data and existing subscriptions, and with "don't buy things until a measured bottleneck justifies it."

CRSP is genuinely the correct choice for survivorship-bias-free research; the specialists aren't wrong. But nobody priced it. Options are: accept the cost, find a cheaper substitute for delisting/corporate-action data and accept degraded rigor, or restrict the first slice to instruments where survivorship bias is not a factor. **A three-instrument slice of SPY/QQQ/MSFT arguably does not need CRSP at all** — none will delist during the test window, and dividend-adjusted total returns are available free. My read: defer CRSP until the universe actually expands. Flagging rather than deciding.

---

## 1. Label contract — PROPOSED, complete

The single hardest blocker from V0.1, now specified.

| Element | Proposed value |
|---|---|
| Prediction target | Binary sign of 5-trading-day forward **excess** total return vs. SPY. `y = 1` if `Σ log(1+RET_i) − Σ log(1+RET_SPY) > 0` over closes t → t+5, else 0. For SPY itself, use absolute forward total-return sign. |
| Horizon | 5 trading days |
| Return convention | Log total return, official close-to-close, t close → t+5 close |
| Decision clock | **15:45:00 America/New_York.** Decision on day t may use completed daily bars through t−1, plus intraday/event data with `available_time <= 15:45 ET on t`. The forward label begins at the official t close. |
| Corporate actions | Compound daily `RET` rather than differencing adjusted prices. Splits via adjustment factors; ordinary and special dividends included; spinoffs via distribution processing. If an action cannot be deterministically valued → `label_status = CORPORATE_ACTION_UNRESOLVED`, observation excluded before fitting. |
| Delisting | Compound final regular return with delisting return: `(1+RET)·(1+DLRET) − 1`, terminate path at delisting date. If `DLRET` absent → assign −100% from last valid close and set `delisting_return_imputed = true`. |
| PIT universe membership | Frozen CRSP vintage keyed by PERMNO, identified in the run manifest. Ticker changes resolved through names history. **Never reconstruct membership from current constituents.** |

Two things worth noticing. The 15:45 decision clock deliberately leaves a 15-minute gap before the close — you decide at 15:45 but the label starts at the 16:00 close, so the model cannot use the closing print it is being scored against. And using *excess* return vs. SPY rather than raw return means the model must beat the market, not merely rise with it, which is the correct bar for something that will later buy options.

---

## 2. Reproducibility contract — PROPOSED, complete

**Bit-for-bit equality required** for: canonical input snapshots, configuration, universe membership, split/embargo assignments, row identifiers and ordering, non-floating values, missingness patterns, discrete decisions, frozen-prediction records, canonical model state, artifact indexes.

**Tolerance comparison** for floating-point features, parameters, scores, probabilities, valuations, metrics — elementwise with identical keys and shapes:

```
abs(a − b) <= 1e-12 + 1e-9 * max(abs(a), abs(b))
```

NaN locations must match exactly. RNG algorithm, seed, path count, and thread count must match. **A differing environment fingerprint yields `UNTESTED`, not a tolerance-qualified pass** — this is the right call; it refuses to launder an environment change as a rounding difference.

**Frozen-prediction immutability** (the quiet risk flagged in V0.1, now specified):
- Each prediction stored as an append-only RFC 8785 canonical-JSON envelope, SHA-256 hashed
- Uniqueness on `(model_id, instrument_id, decision_time_utc, horizon_trading_days, input_manifest_sha256)`
- `UPDATE` and `DELETE` rejected; conflicting rewrites rejected
- `prediction_sha256` verified on every read
- Upstream revision creates a **new** `vintage_id`, manifest, and `prediction_id`; corrections use `supersedes_prediction_id` and preserve the original

That closes the failure mode where a historical decision silently changes after a data revision while the audit trail still looks intact.

**Manifest fields** (~40): schema version, run/test IDs, created/started/finished timestamps, `decision_time_utc`, `as_of_utc`, repository revision, `worktree_dirty`, worktree diff hash, command, working directory, exit code, environment fingerprint, OS, architecture, hardware fingerprint, container image digest, runtime versions, dependency lock hash, timezone, locale, pipeline config hash, label contract version, feature schema hash, RNG algorithm/seed, thread count, model ID, model artifact hash, universe snapshot hash, corporate actions snapshot hash, parent manifest hash. Plus `inputs[]` (source, provider version, dataset ID, vintage ID, availability cutoff, sha256, row count) and `outputs[]` (artifact ID, media type, schema hash, sha256, row count).

---

## 3. Lineage resolution — PROPOSED, complete

Two records share a `lineage_cluster_id` **only** by the first satisfied rule:

1. Same `original_source_id` + source-native `original_event_id` (revisions stay one event)
2. Explicit `syndication_parent_id`, `revision_of`, canonical URL, or upstream reference resolving to that tuple
3. Exact SHA-256 match of canonicalized substantive content, excluding transport metadata, timestamps, provider wrappers
4. Versioned human adjudication record

**Fuzzy similarity may nominate candidates but never auto-merge.** Correct — an automatic fuzzy merge is exactly how independent corroboration gets silently erased.

Disputed lineage representation: preserve separate `record_id`s, set `lineage_status="DISPUTED"`, `lineage_cluster_id=null`, plus `candidate_lineage_cluster_ids[]`, `lineage_match_method`, `lineage_evidence_ids`, `lineage_reason_code`, `lineage_resolution_id=null`. Excluded from novelty/independence calculations until adjudication sets `CONFIRMED`. Original never rewritten.

This refines what I implemented earlier tonight — my version treated unknown lineage as a single `UNKNOWN` sentinel; theirs is a proper state machine with candidate tracking. Theirs is better and should replace mine.

---

## 4. Still open

- **D — Option valuation/exit contract.** No response this round. Still needs: joint spot/IV path model for EV, deterministic exit policy (profit target, stop, DTE time stop), early assignment and dividend handling. Without this, option EV and probability-of-profit are unsupported numbers.
- **F — Audit packet.** No response this round. Needs canonical frozen-response hashing and the round-1 blind/withheld split.
- **Historical options data.** Unchanged and still the top project risk. No provider has been identified, priced, or sampled. Nothing honest can be backtested on options until this is resolved.
- **4-way split isolation.** Train/tune/calibration/untouched-final-test with exactly-once final evaluation. Purge and embargo are implemented and tested; the four-way isolation is not.

---

## 5. Implementation status

`mp_v01/` — 33 tests passing, zero dependencies, `python run_all.py`.

Built and verified: point-in-time store with enforced no-lookahead, four-timestamp evidence schema, bitemporal revision vintages, syndication collapse with conservative unknown-provenance handling, execution cost model with stale/wide quote rejection, walk-forward splits with horizon-tied purge and embargo, deterministic risk gates emitting only PASS / WATCH / PAPER_TRADE_CANDIDATE.

Not built: any market data connection, any strategy, any backtest result. **No edge has been demonstrated or claimed.**

---

## 6. Decision list for Tyler

1. **First slice: accept `INDEX_PLUS_ONE` (SPY/QQQ/MSFT) or hold to semiconductor-first?** Unanimous specialist recommendation is the former. Gates everything.
2. **CRSP:** subscribe, substitute, or defer until the universe expands beyond three non-delisting instruments?
3. Accept the label contract in §1 as written, or amend the horizon/target?
4. Accept the reproducibility contract in §2 as written?
5. Re-run SPEC-ROUND for the two silent domains (options valuation, audit packet)?

---

## Decision log
- 2026-08-12: V0.1 approved by Tyler, then materially revised by REVIEW-002 findings.
- 2026-08-12: `PAPER_TRADE` renamed `PAPER_TRADE_CANDIDATE` — analysis nominates, gates authorize.
- 2026-08-12: Unknown provenance counts as zero corroboration (implemented); superseded in spec by the fuller DISPUTED state machine (not yet implemented).
- 2026-08-12: First-slice vote unanimous for `INDEX_PLUS_ONE`, contradicting Tyler's prior approval of semiconductor-first. **Unresolved.**
- 2026-08-12: Label and reproducibility contracts specified. CRSP dependency introduces an unpriced, unapproved cost.
