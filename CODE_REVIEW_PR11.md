# PR #11 review: diagnostic integrity, contract research and desktop themes

Reviewed against main `5dd9e9ecdc6b8840182ff6500de2d8d2f63fdfcc` and the PR's
initial revisions. This is a paper-research patch, not a finding of predictive
edge or authorization to trade real money. The PR remains a draft for review.

## CI incident and correction

The September 5 local / September 6 UTC failures were caused by our new test
`expired_true_is_not_claimed_verified_without_an_expired_sample`. Its supposedly
future fixture expired on **2026-01-16**, already in the past when CI ran. The
production comparison correctly classified it as expired; the assertion was
wrong. The fix freezes the fixture's observation clock at 2025-09-05, and a
separate regression checks the same expiry against clocks in 2025, 2026 and
2030. It does not change production time or weaken the expected behavior.

Commit `c1cefff68316a48debb9d4f0009d7bed1dd29776` passed all six jobs in
[replacement CI run 34005284956](https://github.com/tylerj-spec/MoneyPrinter/actions/runs/34005284956).
This result applies to that commit, not automatically to later feature commits.
GitHub's matrix fail-fast behavior accounted for the cancelled sibling jobs;
`fail-fast: false` now retains each interpreter's independent result. Failures
are not ignored and no `continue-on-error` setting was added.

## Findings addressed

| Priority | Location | Finding and change |
|---|---|---|
| High | `massive_options.diagnose_access` | The original ladder treated plausible expirations as proof of `as_of`, and did not actually validate the expired toggle. The revised ladder checks explicit scope, reports uncertainty, and never certifies historical quote access. |
| High | `massive_options._get` | An HTTP 401 was called an entitlement refusal, malformed JSON could crash, and error-body truncation could expose part of a credential. Authentication, denial, throttling, transport and shape errors are now separate; untrusted error bodies are not printed. |
| High | `massive_options._get` | Default redirect behavior was unsuitable for credential-bearing requests. Redirects are refused, authentication is an unredirected header, and TLS verification remains enabled. |
| High | `strategy.picks.select_contract` | Only the first row's required keys were checked; NaN, booleans, crossed prices and malformed later rows could evade validation or crash selection. Every eligible candidate is independently screened before ranking. |
| Medium | `strategy.contract_selection` | The initial new ranking module was unconnected, had a prose/key ordering mismatch, and could choose an excessively distant delta for cheapness. It is now integrated and versioned. The original nearest-delta policy stays the default; the cost-aware policy is opt-in and falls back to nearest delta outside its band. |
| Medium | `generate_picks` / `strategy.picks` | New records freeze selection policy, selected metrics, eligible count, up to five alternatives, baseline/challenger identities and a fingerprint of the prepared inputs. The envelope version is 0.4.0. Existing files are not rewritten. |
| Medium | `export_research` | Added separate JSONL input and outcome views, joined by immutable row IDs, with checksums, rejection reporting and deduplication. Decision inputs come only from the frozen record. Outcome values are never input features. |
| Medium | `fetch_massive._write` | Second-resolution filenames plus overwrite writes could replace an earlier fetch. New fetches use microsecond names and exclusive creation. |
| Usability | `gui` / `ui_theme` | Light/dark choices persist without persisting credentials. The console, controls, menus and help window are themed. Workflow buttons wrap to keep Stop visible. OS-native window decorations/dialogs retain OS appearance. |

## What the five-rung diagnostic actually establishes

Every request uses `sort=ticker`, `order=asc`, `limit=3`. Sorting by expiration
alone was not a deterministic tie-break because many contracts share an expiry.
Even a unique sort does not prevent vendor updates between calls.

1. Bare endpoint response.
2. Add `underlying_ticker` and check the returned underlying.
3. Add `expired=true` and look for evidence of expired-contract access.
4. Add `expiration_date.gte` and check **every returned expiry** against that bound.
5. Add `as_of` and compare the valid sample to the preceding valid, nonempty sample.

An absent response array is allowed as empty by the documented response schema;
a wrongly typed array or malformed row is rejected. Missing/invalid dates are
`INVALID_RESPONSE`, not evidence that a filter was ignored. A preceding empty
or invalid sample cannot establish a positive `as_of` effect.

The diagnostic does not independently verify listing dates, complete history,
`expired=false` behavior, prices, NBBO quotes, or executable fills. It makes no
pagination or aggregate-bar calls. It makes at most five requests separated by
13-second pauses, stops after a transport/service/shape refusal, and saves no
market data. Another process using the same key can still cause rate limiting.
Do not run a fetch concurrently with the diagnostic.

| Verdict | Meaning / action |
|---|---|
| `OK` | This sample passes the named mechanical check. Not proof of all data or all filters. |
| `CONSISTENT` | Adding `as_of` changed a valid uniquely sorted sample while scope still matches. Suggestive, not independent historical verification. |
| `UNVERIFIED` | The sample did not demonstrate the capability. An unchanged sample does not prove an ignored filter. Do not launch a bulk backfill. |
| `EMPTY` | No rows. Could be coverage, scope or access; do not infer a paid-plan requirement merely from emptiness. |
| `IGNORED` | Returned underlying or expiry contradicts an explicit requested bound. Do not trust that response for research. It identifies a contradiction, not the vendor's internal root cause. |
| `AUTH_FAILED` | HTTP 401: check the credential. Not an entitlement diagnosis. |
| `NOT_ENTITLED` | HTTP 402/403: access denied. Inspect permissions/plan; this alone does not prove the key is valid. |
| `RATE_LIMITED` | HTTP 429: stop concurrent requests and retry later. No automatic retry or subscription inference. |
| `UNREACHABLE` | No usable HTTP response: network, DNS, TLS, proxy or timeout. |
| `INVALID_RESPONSE` / `REDIRECT_REFUSED` | Invalid response shape/encoding or a blocked redirect. No historical capability established. |
| `HTTP_ERROR` | Other HTTP failure. Read the status code; no speculative entitlement claim. |

`POINT_IN_TIME_CONSISTENT` is the CLI summary only when all preceding checks
passed and the final rung is consistent. It exits zero to indicate a completed
limited diagnostic, **not approval for automated historical trading**. All
uncertain/failed summaries exit nonzero. No key means no request is sent.

### Safe Windows commands

From the repository root in PowerShell, with Python and `tzdata` installed:

```powershell
py -3 -X utf8 .\run_tests.py
py -3 -X utf8 .\fetch_massive.py --diagnose --tickers SPY --as-of 2025-08-01 --prompt-key
```

The second command asks for the key in a hidden prompt. It does not put the key
in command history, a file, or the command-line arguments, and restores the prior
process environment afterward. The key necessarily exists in process memory
while used; this is not protection against a compromised machine. A terminal
without a secure prompt is refused instead of falling back to echoed input.
The masked GUI key box is the other supported session-only path. Do not paste
credentials into chat, GitHub issues, screenshots or output attachments.

## Measurement loop and the contract policy

The `delta` baseline remains the default. `cost_aware` is a named experiment, not
an empirically optimized model. Within a +/-0.08 absolute-delta band it ranks by
estimated round-trip cost / entry premium, delta gap, negative-theta burden /
premium, distance from a 40-calendar-day DTE assumption, spread, OI and volume.
Outside the band, nearest delta takes priority over cheapness. Stable contract
identity breaks ties. Positive theta is not mislabeled as a decay burden.
Unknown optional Greeks remain null. The common hard screens are not relaxed.

```powershell
py -3 -X utf8 .\generate_picks.py --selection-policy delta
py -3 -X utf8 .\generate_picks.py --selection-policy cost_aware
py -3 -X utf8 .\export_research.py
```

Generation retains the existing same-day, unbackdated forward-record rules.
Both policy runs on one date are **paired research observations**, not twice the
independent evidence. No component weights change in this PR. The top-five
alternative identities are useful audit context, not a complete counterfactual
backtest: alternate contracts are not automatically resolved as trades.

Each research export creates a new directory under `MoneyPrinterData/research`:

- `inputs.jsonl`: frozen decision features, policy, contract metrics and hash-based row ID.
- `outcomes.jsonl`: separate resolver outputs, observed/modelled/mixed provenance,
  evaluation time, and a conservative outcome-availability time equal to export time.
- `manifest.json`: hashes, source identities, rejection/duplicate reporting and limitations.

Abstentions and unresolved cases are kept, never assigned zero profit. Corrupt
records are rejected. Legacy 0.1 files still verify in the existing app, but their
unprotected metadata is excluded from this training-oriented export. The exporter
never rewrites them. Outcome data without availability timestamps is not silently
used to bridge missing periods. An export is a research view, not a model ready
to be trained by blindly concatenating all columns.

## Remaining blockers before trusting profitability

**Live-data verification is still outstanding.** No user API key was supplied
or used. Offline fixtures and a stored connector snapshot test software behavior,
not vendor entitlement or an actual executable market. The stored OptionsCalc
snapshot lacks bid/ask, volume, OI and exact quote timestamps; it remains
ineligible and those fields are not invented.

**An equity excess-return forecast is not an options profit forecast.** A stock
can outperform SPY while falling, and a correctly predicted stock direction can
still lose money in a long option due to premium, time and volatility changes.
The app needs an out-of-sample, cost-aware options return distribution before
claiming calibrated probabilities of profitable trades. Delta, OI and IV are
not substitutes for that model.

**Quote timing, market calendars and model marks remain limitations.** The current
pipeline still uses prior available daily underlying closes for some Greeks,
does not have a complete exchange holiday/early-close execution calendar, and
cannot prove quote age/fill size on each snapshot. The resolver's Black-Scholes
fallback assumes entry IV, a fixed rate and zero dividends; it is not a verified
American-option execution model. Sparse daily marks do not establish intraday
stop/target fills. Modelled and mixed paths must not be pooled as observed profit.

**Data vintage and selection bias require more work.** Hashes detect changes,
not independently attest generation time. Retrospective vendor bars can include
revisions or corporate-action restatements; modeled availability timestamps do
not recreate the original vendor vintage. Universe changes, delistings and
adjusted deliverables need explicit treatment. The current 100-share multiplier
is an assumption for standard contracts, not universal contract validation.

**Validation must precede tuning.** Pre-register a small hypothesis set, keep a
chronological untouched holdout, purge/embargo overlapping label horizons, group
uncertainty by decision date/underlying, and correct for trying multiple policies.
Compare net expectancy, drawdown/tail losses, calibration and stability by market
regime, not just hit rate. Reserve fresh forward periods after each weight change.
Add point-in-time earnings/dividend/event calendars, contemporaneous bid/ask and
sizes, IV term structure/skew and cost assumptions before noisy social inputs.
None of these inputs should be reconstructed with information from after a decision.

**Risk gates are not broker authorization.** Candidates continue to carry the
risk gate's abstaining result where evidence, post-cost edge or sizing is absent.
This PR adds no broker connection, order path or real-money mode.

## External references checked during this review

- [Massive All Contracts documentation](https://massive.com/docs/rest/options/contracts/all-contracts):
  `as_of`, expired contracts, expiration filters, ticker sorting and optional response arrays.
- [Python urllib.request documentation](https://docs.python.org/3/library/urllib.request.html):
  redirect handlers and unredirected authentication headers.
- [GitHub matrix documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations):
  fail-fast cancellation behavior.
- [Options Industry Council: option price behavior](https://www.optionseducation.org/referencelibrary/faq/option-price-behavior):
  option values depend on more than underlying direction.
- [Options Industry Council: theta](https://www.optionseducation.org/advancedconcepts/theta)
  and [vega](https://www.optionseducation.org/advancedconcepts/vega):
  time and volatility sensitivity, not validated predictors of profit.

Repository-specific findings above come from the inspected code and regression
executions, not from a claim that these external sources endorse the strategy.
