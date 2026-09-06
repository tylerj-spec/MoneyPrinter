# Historical options replay

`python replay_options.py --demo` runs deterministic SYNTHETIC data, writes a
new local output directory, and creates short pick justifications with expandable
indicator/weight/contract details. `review.html` shows the baseline and
`review_1.html` shows the challenger. The exact decision-time input slice is a
clickable JSON file. Future execution quotes do not enter that slice.

For your licensed quote history:

```powershell
.\.venv\Scripts\python.exe -X utf8 .\replay_options.py --dataset C:\Data\replay.json
```

Use the demo's generated `dataset.json` as the documented schema example, not as
market data. Change provenance to `USER_SUPPLIED_QUOTE_HISTORY` only for real
observations. Every quote needs contract_id, bid/ask and sizes in CONTRACTS,
observed_utc, available_utc, source, feed_type and delayed=false. Entry snapshots
also require open_interest, volume, oi_available_utc and volume_available_utc.
Underlying observations use contract_id equal to the ticker and require a
contemporaneous consolidated quote. All times include timezones.

Supply contract listing/known timestamps, explicitly verified standard 100-share
specifications, a dated interest-rate input/assumption, and an authoritative
session schedule already known at each decision. The replay does not infer a
complete holiday calendar from weekdays. It refuses adjusted/ambiguous contracts.

Each decision pre-registers ticker, decision_utc, exit_utc and optional variant.
Entries and exits use a new quote at least one second after submission and within
60 seconds, inside the supplied session. One contract crosses at ask/bid with an
explicit assumed $0.80 fee each way. Missing entries are NO_ENTRY_FILL; missing
exits stay UNRESOLVED, not zero and not modelled.

This version uses scheduled exits only, not intraday stops/targets. Paired policy
results are independent one-contract counterfactuals, NOT a combined portfolio.
Greeks are European Black-Scholes estimates with zero dividends; actual quote
marks determine returns. This is not a verified American-option/dividend model.
Local checksums detect changed files, not false vendor provenance or retrospective
vintage reconstruction. No real market history or paid quote entitlement is
included in the repository.
