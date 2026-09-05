# Review of the September 5 app run

Reviewed base: `de51e1b37c1b9f7733e6aeed7ed008ed2e24a1b2` on `main`.
Scope: the supplied console/dashboard output and the fetch, screen, generate,
resolve, export, dashboard, and desktop workflow behind it. This is a code and
workflow review, not validation of a profitable strategy.

## Findings and fixes

| Priority | Finding | Evidence and change |
|---|---|---|
| P1 | Expiration selection can exclude the entire permitted entry band | `fetch_data.py` took `tk.options[:6]`, while `RiskLimits` requires 21–60 DTE. Six daily expirations can all be below 21 days. Fetch now covers all listed expirations through 60 days, including nearer dates needed to mark existing positions. It reports the number of contracts inside the entry band. One failed expiry no longer discards a ticker's other successful responses; an empty fetch no longer supersedes a usable snapshot. |
| P1 | A forward record could use a future chain or an arbitrary historical decision date | `generate_picks.py` selected the newest chain without comparing its observation time with the decision cutoff. The CLI now refuses backdated/future forward records. It selects a chain available by the earlier of the generation time and the 15:45 ET cutoff, requires a same-day snapshot for a proposal, and records weekend abstentions. Chain availability is stamped after the ticker's final response, not before the network requests. |
| P1 | Massive returned implausible historical contracts but the probe reported success | The supplied run requested SPY as of 2025-08-01 and printed contracts expiring in 2012. The adapter accepted `status=OK` without validating the requested scope. Probe and backfill now check underlying, positive strike, required fields, and expiration on/after the requested date; mismatches fail instead of entering the store. Requests also specify `expiration_date.gte`. |
| P2 | The Massive probe overstated what it verified | One call to the contract-reference endpoint cannot establish access to historical price bars. A successful probe now explicitly means matching reference data only; an empty result is inconclusive. Pagination that reaches its cap with more pages outstanding fails instead of silently returning incomplete history. Fetch failures now yield a nonzero exit status. |
| P2 | Output locations depended on the button, script, and old GUI settings | The log's data workbook went to an old ZIP checkout, while picks and backtests went inside the Git checkout. Shared paths now default to `~/MoneyPrinterData`; the GUI and CLI use the same folder. Data, JSON picks, both workbook types, backtests, dashboard, and development report have external defaults. The GUI can change the common root. Migration copies recognized old outputs and preserves originals and same-name conflicts. Diagnostics inspect both workbook folders. |
| P2 | The picks workbook gave no useful starting point when all variants abstained | The run had zero proposals and 20 abstentions. `Pick_History` therefore had no proposal rows. A picks workbook now opens on `Pick_Runs`, showing counts and an explicit `NO PROPOSALS` result. All abstentions retain their reason, source file and integrity status. Rejection reasons include overlapping counts for DTE, spread, open interest, volume, and unmodellable Greeks. No trades are invented to fill an empty sheet. |
| P2 | The checksum did not protect record metadata, and the dashboard did not verify it | The original checksum covered only the picks array. Version 0.2 also hashes the envelope, including dates, sources, and policy. Original 0.1 records remain readable using their original picks-only checksum. The dashboard checks integrity and labels invalid records `VOID`. New pick files use microsecond timestamps and exclusive creation. A checksum is described as a content check, not proof of creation time. |
| P2 | Historical-options GUI action crashes after the date prompt | `fetch_massive()` called undefined `valid_date`. It now uses the existing validator and normalizes accepted dates before invoking the CLI. Busy menu actions also preserve the active job's output state, and child processes consistently use UTF-8 on Windows. |

The exact reasons all MSFT and NVDA contracts failed cannot be reconstructed
from the pasted summary: their raw option snapshots were not attached. The
expiration bug is confirmed in code and reproduced with daily expirations;
the new failure counts make the next run diagnosable without guessing.

## What the supplied results mean

All five variants in the supplied run returned `NO_EDGE`. Their accuracies
(about 50.6–51.8%) were below the reported 54.67% majority-class rate. The study
contained only three non-benchmark instruments. The infrastructure fixes do
not change these measurements or establish a trading edge. Risk thresholds,
variant weights, the signal-study algorithm, and the paper-only gate remain
unchanged.

September 5 was a Saturday. New runs on weekends now explain why there is no
new paper entry, even if a provider returns cached option quotes. Re-fetch
market data during a trading session before the cutoff to collect the
correct expiration range, then generate a new run. The old zero-pick record
should remain in the history.

## Verification

`python run_tests.py`: **259 tests passed** locally with Python 3.12.13 and
openpyxl available: 244 existing/harness tests and 15 run-regression tests.
The changes add 19 tests relative to the reviewed base (15 regressions, three
GUI checks, and one dashboard integrity check). Core offline demonstrations
also completed. `git diff --check` passed.

Regression fixtures cover:

- Six near expirations followed by valid 21–60 DTE contracts; partial and
  empty provider responses; post-fetch observation timestamps.
- Actual screen failures and their explanations, cutoff selection, stale
  chains, weekend abstention, and rejection of backdated forward records.
- The anomalous 2012 Massive response, reference-only capability claims,
  and incomplete pagination.
- Metadata tampering, backwards-compatible reading of original pick files,
  external paths, migration conflicts and repeatability, and CLI operation
  from another working directory.
- A frozen zero-proposal workbook with 20 abstentions, plus a valid weekday
  contract that reaches the JSON record, history and justification sheets.
  The latter mocks component scores to isolate the pipeline and confirms
  the risk gate still says `PASS` (do nothing).
- The historical-options GUI action, child output-path propagation, busy
  action state, and dashboard integrity warnings.

The GUI checks are headless. Live Yahoo/Massive requests and the user's local
Windows install were not rerun here. No API key or local market-data folder
was supplied, and no generated market data or credentials are part of this
change. Existing GitHub Actions run the full suite on Linux and Windows.

## Remaining research limits

- Weekend detection is not a complete exchange calendar. Holidays, early
  closes, and verified quote ages still need explicit session handling.
  Same-day Yahoo retrieval is not proof of a fresh executable bid/ask.
- Greeks still use a previously available daily underlying close. That
  price may differ from the spot at the option quote, affecting solved IV
  and Greeks. Paper mark assumptions remain visible in the resolver.
- Historical studies use today's available bar vintages with assumed
  publication lags, not a complete archive of historical revisions. These
  changes do not establish full point-in-time provenance for that history.
- Massive's reference response is checked for consistency, but provider
  `as_of`/`expired` semantics and complete universe coverage still need a
  live reconciliation. Stored Massive aggregates are trade bars, not
  historical bid/ask chains, and the current pricing/resolution pipeline
  does not consume them. An options backtest is still unimplemented.
- Local hashes detect a mismatch; a person able to edit the files can also
  recompute their hashes. Independently retained snapshots or trusted
  timestamps are needed to substantiate when a prediction existed.

The Massive API distinctions were checked against the vendor's
[All Contracts documentation](https://massive.com/docs/rest/options/contracts/all-contracts)
and [Custom Bars documentation](https://massive.com/docs/rest/options/aggregates/custom-bars).

## Review and rollout

Review the pull request before merging. After updating the local checkout,
start `run_gui.bat`. The GUI copies recognized legacy outputs, shows the new
root, and writes future outputs there. Existing files are preserved; inspect
the copied records before removing old copies. If using the CLI, run
`python migrate_outputs.py` once. An old ZIP checkout can be imported with
`--from-code-dir`.

The default Windows location is `%USERPROFILE%\MoneyPrinterData`. Use the
GUI's Output folder control or `MONEYPRINTER_HOME` to select another location.
Keep backups of that output folder separately from the source repository.
