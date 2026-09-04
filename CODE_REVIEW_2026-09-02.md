# Money Printer — follow-up code review

**Date:** 2026-09-02
**Reviewer:** Claude (adversarial review pass, second)
**Scope:** whole repository at commit `af1a059` — 4,595 lines of Python
**Prior review:** `CODE_REVIEW_2026-08-13.md`
**Method:** all eleven findings below were reproduced by executing code, and each carries the actual output. **3.1** was resolved on 2026-09-02 by a live fetch on Tyler's machine after the review environment's network policy blocked Yahoo; the assumption it questioned holds, and the finding is downgraded rather than closed — see below.

---

## 0. Headline

> **Status 2026-09-04.** All eleven findings are now fixed or resolved. §2.1 — the purge gap, the last blocking one — is closed: the purge is counted in trading sessions against a trading-day horizon, and the test that certified the old behaviour has been rewritten. §3.1 is closed too, with a split cross-check that is pure and runs offline. **Nothing blocks a Phase 3 null run on real bars.**

The 2026-08-13 review was accurate. Three weeks later, its three blocking findings are **still live in `main`** (§2 below). That is the single most important fact in this document: the problem is not that these defects are unknown, it is that knowing about them has not yet changed the code.

Three further defects were found that the prior review did not cover (§1). All three sit in `mp_v01/` — the system of record, the careful one — and all three fail in the same direction: **toward more apparent evidence, more apparent data, and fewer refusals.** That is the expensive direction for a project whose stated default is abstention.

One new detail sharpens §1.1 of the prior review considerably: **the test suite certifies the bug.** See §2.1.

---

## 1. New blocking bugs — ALL THREE FIXED 2026-09-02

Not covered by the 2026-08-13 review. All three were in `claude/app/mp_v01/`, and all three are now fixed with regression tests verified to fail without their fix. The descriptions are kept in full: the reasoning is the durable part.

### 1.1 Two revisions of one record both survive `as_of()` — FIXED
`src/pit/store.py` — `add()` / `as_of()`

`add()` tracks supersession in a plain dict:

```python
self._superseded_by[rec.supersedes_record_id] = rec.record_id
```

When a **second** revision also supersedes the same original, that assignment overwrites the first. The first revision is then left with nothing pointing at it, is never marked superseded, and `as_of()` returns it alongside the genuinely current vintage.

This breaks the store's central promise — exactly one vintage is current at any decision time — and it breaks it silently. Downstream, the duplicate inflates `independent_information_events()`, which feeds the evidence gate in `gates/risk.py`. Two copies of one macro print read as two independent confirmations.

Realistic trigger: a BEA advance estimate, then preliminary, then third estimate, all keyed to the original release. Anything revised more than once hits this.

**Reproduced:**

```
v0 = 1.0  (original)
v1 = 2.0  supersedes v0
v2 = 3.0  supersedes v0   # second revision of the same record

records returned as_of day+5: [('v1', 2.0), ('v2', 3.0)]
expected exactly one current vintage; got 2
```

**Fixed 2026-09-02** by rejecting a second supersession of an already-superseded record at `add()` time, with an error naming the record to chain from. A set would not have been enough: it stops the original being returned, but leaves two sibling revisions both current and neither superseded. Resolving that by guessing (say, latest `available_time` wins) would be inference; rejecting it is not. Two regression tests, both verified to fail without the fix: the ambiguous case raises, and an honest three-vintage chain still returns the vintage live at each decision time.

### 1.2 An assumed −100% delisting return is labelled `OK` and marked usable — FIXED
`src/labels/contract.py` — `build_label()`

When a delisting has no `DLRET`, the contract appends `-1.0` — a total loss it did not observe — and correctly sets `delisting_return_imputed=True`. It then overwrites the status back to `OK`:

```python
status = LabelStatus.DELISTED_IN_HORIZON if delisted_in_horizon else LabelStatus.OK
...
if status == LabelStatus.DELISTED_IN_HORIZON:
    status = LabelStatus.OK
```

So `is_usable()` returns `True`, and a fabricated observation flows into training indistinguishable from a real one. The flag exists, which shows the intent was right — nothing downstream reads it.

Everywhere else in this file an unresolved condition yields `y=None`. This is the one place a guess is dressed as a measurement, which is a direct departure from the project's "nothing is ever invented" rule.

**Reproduced:**

```
status=OK   y=0   excess=-inf
imputed=True   is_usable()=True
```

**Fixed 2026-09-02** by having `is_usable()` consult `delisting_return_imputed`. The flag was already set and simply unread. A delisting carrying a real DLRET is an observation and stays usable; only the assumed total loss is excluded.

### 1.3 The risk gate raises instead of failing closed — FIXED
`src/gates/risk.py` — `need()` and the threshold comparisons

`need()` handles `None` and NaN carefully — the NaN guard is genuinely good, with a comment explaining that an unguarded NaN slides past every threshold, and there is a test for it. It does **not** handle a value of the wrong type.

A candidate arriving from JSON, a model response, or a spreadsheet with `"35"` instead of `35` reaches `limits.min_dte <= dte` and raises.

The module's whole premise is that it is the last deterministic thing between a model's proposal and a decision. **An exception is not a decision.** Whatever calls it either crashes or catches broadly, and a broad catch around the risk gate is how `PASS` quietly becomes "skipped".

**Reproduced:**

```
candidate = dict(..., dte="35", ...)   # everything else valid

RAISED TypeError: '<=' not supported between instances of 'int' and 'str'
```

**Fixed 2026-09-02** by rejecting non-numerics the way NaN is rejected: `invalid_type:{key}` into `failed`, which routes to `PASS`. Applied to `need()` and to the three optional sizing fields. `bool` is excluded explicitly — it subclasses `int`, so `True` would otherwise compare as 1 against every threshold.

---

## 2. Previously identified, still live in `main`

These restate the 2026-08-13 review. They are repeated here with reproductions because a reproduction is more actionable than a description, and because three weeks have passed.

### 2.1 Purge gap counts calendar days — and the test certifies the bug — FIXED 2026-09-04
`src/backtest/walkforward.py` — see prior review §1.1

The prior review is correct. What it does not say is that **the test suite asserts the buggy behaviour is right**:

```python
# tests/test_backtest_and_gates.py:26
ok = Split(0, D("2024-01-01"), D("2024-06-01"), D("2024-06-06"), D("2024-07-01"))
ok.validate(5)   # 5 CALENDAR days, asserted to pass
```

The guard and the test proving the guard works share the same wrong assumption. That is why 76 green tests report no problem.

A second symptom, also unmentioned: `make_splits` has **no trading-calendar awareness at all**. The first split it generates ends training on a Saturday and opens testing on 4 July, a market holiday. `train_days=180` is not 180 trading days either.

**Reproduced — first split from the default call:**

```
train_end   2024-06-29 (Sat)
test_start  2024-07-04 (Thu — market holiday)
calendar gap enforced: 5 days  -> validate() passes

a label decided on train_end resolves 6 calendar days later,
i.e. 2024-07-05 — which is 1 day INSIDE the test window.
LEAK: True
```

**Fixed 2026-09-04.** The purge is now counted in trading sessions, in two places — `Split.validate` and `evaluate._assert_fold_is_chronological` carried the same defect, and fixing one would have left the other certifying leaks.

A new `TradingCalendar` holds the sessions that actually happened. It is built from the dates of the bars you have, because this repository has no holiday table and adding a hand-typed one would be an assumption wearing the costume of data. A consequence worth stating: a gap in your data is indistinguishable from a closure, so the purge over-drops rather than under-drops, which is the safe direction.

**The rule, stated precisely.** A label decided on session `i` resolves at session `i + H`, so the test window may open no earlier than `i + H + 1` — H whole sessions strictly between the last training session and the first test session. Opening *on* `i + H` is already a leak: that session's close determines the training label's outcome and is not known at the 15:45 ET decision on the same day.

**`calendar` is a required argument, not an optional one.** A guard that cannot count what it claims to check should refuse rather than approximate, so `validate(5)` is now a `TypeError` at the call site and a fold carrying decision times but no calendar raises `LeakageError`. The old code's failure mode was worse than being wrong: it was *confidently* wrong, reporting a verified purge it had no way to verify.

**The second symptom is gone too.** `make_splits` now lays splits out in session-index space, so every boundary is a real session by construction. It previously ended training on Saturday 2024-06-29 and opened testing on 2024-07-04, a market holiday, because it only ever added timedeltas. Its size parameters are now counts of sessions, not calendar days — `train_sessions=180` is roughly nine months, not six.

Five new tests, and the reviewer's prescription was followed: the arithmetic was reverted afterwards to confirm `purge_gap_is_counted_in_sessions_not_calendar_days` and `thanksgiving_week_purge_that_calendar_arithmetic_called_safe` both fail without the fix and pass with it. `purge_gap_prevents_label_horizon_bleed` was rewritten rather than preserved, as instructed. Its replacement needs no holiday at all to make the point — Fri 2024-03-15 to Fri 2024-03-22 is 7 calendar days and 4 sessions, so an ordinary weekend was always enough to defeat the old rule.

One thing the fix surfaced that the review did not anticipate: a UTC-midnight datetime is the *previous* session in New York, so `2024-11-28T00:00:00Z` names the 27th. Real timestamps in this codebase (16:00 ET closes, 15:45 ET decisions) round-trip correctly, but the old tests used UTC midnight as a stand-in for a day. Session dates are now read in ET, and a test pins that.

### 2.2 The permutation null never refits — FIXED 2026-09-03
`src/backtest/evaluate.py` — see prior review §1.2(a) and §1.2(b)

`predict_fn(feats)` sits inside the permutation loop but takes no labels, so it returns the identical prediction vector on all 200 iterations.

Today this is only wasted compute, which is precisely why it is dangerous: the noise floor still reads `NO_EDGE` on random data, so the harness looks trustworthy. It stops being harmless the moment a fitted model is plugged in — the null must include the fitting procedure's capacity to overfit shuffled labels.

**Reproduced — instrumented probe, 4 folds, 50 permutations:**

```
predict_fn calls: 204   (4 scoring + 4×50 permutation)
distinct feature inputs ever passed: 1
```

**Fixed 2026-09-03**, and the prior review's §1.2(a) with it — the two were one defect wearing two hats.

**(b) The fit is now in the null.** The interface is `fit_predict_fn(train_X, train_y, test_X)` and folds are `Fold` objects carrying train and test data. Under permutation the model is refit on permuted *training* labels, so whatever a procedure can wring out of noise is priced into the noise floor. A regression test spies on the labels the callback receives and asserts they actually change across permutations.

**(a) The permutation now preserves autocorrelation.** This was the more dangerous half and was still open. Labels are 5-day forward returns computed daily, so consecutive labels share four of five days. An IID shuffle destroys that dependence and makes the null *too tight* — smaller `permutation_std`, larger `z`, smaller `p` — biasing the harness toward reporting edge. Permutation is now over contiguous blocks of `2 × label_horizon`. `block_size=1` still reaches the old behaviour, kept only so the bias can be demonstrated rather than asserted.

`demo/run_noise_floor.py` now measures the distortion on overlapping labels — same strategy, same data, only the null differing:

```
                              null std        z        p
  IID shuffle (the old null)    0.0156    -0.20   0.5572
  block permutation             0.0204    -0.10   0.5622

  The IID null is 23% tighter than the honest one.
```

The demo also gained a genuinely *fitted* strategy — a momentum threshold searched on the training labels — because a fixed rule cannot exercise the refit path at all. All three strategies still read `NO_EDGE` on a random walk, which is the property that makes the harness trustworthy.

### 2.3 The leakage guard is still not in the path — FIXED 2026-09-03
`src/backtest/walkforward.py`, `src/backtest/evaluate.py` — see prior review §1.3

`assert_no_future_features` was defined, tested, and never called by `evaluate_walk_forward`, because folds were bare `(features, labels)` tuples carrying no timestamps to check.

**Fixed** as a consequence of the §2.2 interface change: `Fold` now optionally carries `train_times` and `test_times`, and when present `evaluate_walk_forward` checks them itself — test data strictly after training data, with a purge gap of at least the label horizon. It cannot invent timestamps that were never supplied, but it will no longer let a fold through that trains on the future. A guard you have to remember to call is a guard that eventually doesn't get called.

---

## 3. Medium and low severity

### 3.1 Split adjustment was an undocumented assumption — FIXED 2026-09-04
`src/adapters/yahoo_daily.py` — `daily_total_return()`

**Status: the assumption holds.** Severity downgraded from Medium; the finding stays open on the narrower ground below.

The module argues carefully for `auto_adjust=False` and raw closes plus cash dividends, because vendor-adjusted series get silently restated. That reasoning covers **dividends**. It never mentioned **splits**, and `daily_total_return()` has no split term. The code is correct only if Yahoo's unadjusted `Close` is nonetheless split-adjusted.

**Verified 2026-09-02** on Tyler's machine, live fetch with yfinance 1.7.0, against NVDA's 10-for-1 split effective 2024-06-10:

```
daily_total_return for 2024-06-10 : +0.7461%
independently reported             : ~0.75%
had Close been genuinely raw       : ~ -90%
```

So Yahoo's `Close` is split-adjusted and dividend-unadjusted, which is exactly what this module needs. The assumption is now recorded in the `daily_total_return()` docstring with this evidence.

**What remains.** Documenting an assumption is not testing it. This is still a property of a third-party scraper the repository elsewhere describes as breaking regularly, and if a future change makes `Close` genuinely raw, every split in the history becomes a fabricated ~−90% move that the label contract will faithfully score as real. Nothing in the pipeline would complain.

**Fixed 2026-09-04 — the cross-check, with the review's objection to it removed.** The choice was between a magnitude threshold (simple, offline-testable, but blunt: a genuine −40% earnings collapse is a real observation, and marking it `UNKNOWN` silently deletes exactly the tail events a risk model exists to see) and a split cross-check (precise, no false positives on real crashes, but the review believed it had to live in the live-fetch path and so could not be tested offline).

That last clause turned out not to be true, and it was the only thing making this a tradeoff. **`check_split_adjustment()` is pure** — it takes rows and split ratios and touches no network. Only the *fetching* of `yf.Ticker(t).splits` is live; the judgment is offline and has eight tests behind it. So the precision of the cross-check comes with the testability of the threshold, and there is nothing left to trade.

**How it discriminates.** On the effective date of an r-for-1 split, an adjusted `Close` moves an ordinary amount and a raw one moves by almost exactly `1/r`. For NVDA's 10-for-1 that is +0.75% versus −90% — not a close call. The check fires on the *arithmetic signature* of an unadjusted series, not on the size of a move, which is precisely why a real −40% day on a split date is left alone. There is a test asserting exactly that.

**The repair is surgical, which was not obvious going in.** In a raw series only the return that *straddles* the split is wrong; every other day is priced within one consistent regime and is fine. So a flagged date loses its return and keeps its prices, and the chain continues into the new regime rather than being broken. Dropping the whole series, or even the following day, would be over-correction.

**What it deliberately does not cover.** Splits smaller than 2-for-1 are reported `IMMATERIAL` rather than checked: a 5-for-4's unadjusted signature is a −20% day, which a real session can produce, so flagging it would cost false positives on real moves. That is an acceptable hole because the hazard is a *vendor-wide* change in behaviour, and a vendor that starts serving raw closes serves them for the big splits too. Reporting `IMMATERIAL` rather than skipping silently is the difference between a known hole and an invisible one.

`fetch_data.py` prints the verdict on every fetch — a loud multi-line warning on failure, one line of confirmation otherwise — and writes every check into the vintage file, so a future upgrade that breaks the assumption is caught by the run that breaks it rather than by a −90% move in a workbook months later.

### 3.2 `src/strategy/` is an empty package — FIXED 2026-09-03
`src/strategy/__init__.py` — was 0 lines

Every other package under `src/` is substantive. This one is empty, and roadmap Phases 3 through 5 — null run on real bars, component rank IC, post-cost gate — all assume something lives here to be evaluated. The pipeline can measure a strategy but has nowhere to define one, which is why the demos pass functions inline.

Not a bug. Named because it was the actual blocker between "the machinery is verified" and "Phase 3 can start", and an empty directory appears on no status report.

**Filled 2026-09-03** with `components.py` (point-in-time score components), `variants.py` (five named weight sets, including a deliberately contradictory reversion tilt and a naive equal-weight control), and `picks.py` (contract selection, pre-registered exit policy, generated rationale, and a SHA-256-frozen pick envelope). Driven by `generate_picks.py` and scored by a separate `resolve_picks.py`, which is the roadmap's Phase 6 shape: frozen hashed predictions, scored later by a program that cannot edit them.

None of the components is validated — that remains Phase 4's job, and every pick says so on its face.

### 3.3 Dead branch: both confidence thresholds return `BUY` — FIXED
`market_intelligence_engine.py` — `PredictionEngine.predict()`

```python
if probability[1] > 0.65:
    signal = 'BUY'
elif probability[1] > 0.55:
    signal = 'BUY'
```

The arms are identical, so the 0.65 threshold does nothing and the rule is simply `BUY if p > 0.55`. Residue from the prior review's §2.6 fix that removed `SELL`. Harmless, but it reads as graded confidence and is not.

On the same lines, `prediction = self.model.predict(features)[0]` is computed and discarded.

### 3.4 Six unused imports, three of them heavy — FIXED
`market_intelligence_engine.py` lines 18–31

`os`, `sys`, `Path`, `requests`, `BeautifulSoup` and `StandardScaler` are imported and never used. The last three matter: the module cannot be imported without `requests`, `beautifulsoup4` and `scikit-learn` installed, and uses none of them. `bs4` is a leftover from before the scraper became synthetic.

### 3.5 The two requirements files contradict each other on `yfinance` — FIXED

`requirements.txt` pins `yfinance==0.2.32`. `claude/app/mp_v01/requirements.txt` requires `yfinance>=0.2.40`. **0.2.32 does not satisfy >=0.2.40.** A fresh install that follows the root file produces an environment the pipeline's own requirements declare unsupported, and pip resolves it silently by whichever file was installed last.

This is worse than an ordinary version skew because the root file's comment states the intent explicitly — *"PINNED - yfinance breaks regularly on scraper changes"* — so a reader has every reason to trust the pin. It pins to a version the package it serves rejects.

**Reproduced:**

```
root requirements.txt        : yfinance==0.2.32
mp_v01/requirements.txt      : yfinance>=0.2.40
0.2.32 satisfies '>=0.2.40'  : False
```

Compounding it: `0.2.32` predates several Yahoo endpoint changes, so the pinned version is a poor candidate for actually working against Yahoo today. Current pip resolves `yfinance` to **1.7.0** — five minor versions past either pin, with a changed `auto_adjust` default, which `yahoo_daily.py` sets explicitly and so survives.

**Update 2026-09-02:** yfinance 1.7.0 was confirmed working end-to-end on Windows — a live fetch of SPY/QQQ/MSFT/NVDA produced correct bars, and the split check in §3.1 passed against it. So the working version is 1.7.0 and **both pins are wrong**, not just contradictory. Pin both files to a version that has actually fetched.

**Fix:** pick one version, verify it fetches, and pin it in both files — or better, have the root file defer to the package's own requirements rather than restating them. Whichever version wins needs a real fetch behind it before the pin means anything.

---

## 4. What is genuinely well built

Recorded because the findings above are only worth acting on if the foundation is worth protecting, and it is.

- **`pit/schema.py`** — the four-timestamp contract with causality assertions in `__post_init__`. Rejecting `published_time < event_time` at construction means untrustworthy source timestamps cannot enter the system at all.
- **`as_of()` as the sole read path** — there is no API to filter on `event_time`. Making the wrong thing impossible rather than discouraged is the right instinct and is rare.
- **`gates/risk.py`** — a pure function whose decision is fully explained by `failed_gates`, with no live-order path in the enum. The NaN guard is exactly right (§1.3 above is the one remaining hole).
- **`common/timezones.py`** — replacing a hard-coded UTC−4 with `zoneinfo`. The docstring correctly identifies the old constant as a silent correctness bug in the same family the project exists to prevent, not a cosmetic one.
- **The noise floor, in principle** — validating that the harness reads `NO_EDGE` on a random walk *before* pointing it at anything real is the correct order of operations, §2.2 notwithstanding.
- **`adapters/eodhd_options.py`** — `redact()` scrubs the token from exception text before it can propagate, because request libraries put full URLs in error messages. Someone thought about how credentials actually leak.
- **`CODE_REVIEW_2026-08-13.md`** — the most valuable file in the repository. It documents blocking defects in its author's own work, in specific detail, with fixes.

---

## 5. Recommended order of work

1. ~~**Fix the null first (§2.2).**~~ **Done 2026-09-03**, along with §2.3. The instrument is now calibrated: the fit is inside the null, and the permutation respects label overlap.
2. ~~**Write the failing purge test, then fix the purge (§2.1).**~~ **Done 2026-09-04.** Both purge tests were confirmed to fail against the old arithmetic before the fix was kept.
3. ~~**Close the three fail-closed holes (§1.1, §1.2, §1.3).**~~ **Done 2026-09-02**, along with §3.3, §3.4 and §3.5. Core suite 76 → 81 tests; 105 across the repo.
4. ~~**Decide the split guard (§3.1).**~~ **Done 2026-09-04** — the cross-check, made pure so it tests offline. `yfinance` is pinned to 1.7.0 in both files (§3.5).
5. **Then start Phase 3.** ← **now the top of the list, and unblocked.** With the null fixed and the purge honest this is genuinely informative: run a deliberately worthless strategy on real bars and confirm `NO_EDGE`. Both preconditions are met — §2.1 is closed (a leaky split would have flattered even a worthless strategy) and `src/strategy/` has five variants to run (§3.2).

---

## 6. Fixed since the last review

Delivered on `claude/code-gui-excel-output-q6ur1g`.

- **Prior review §3.6 — CI covered the wrong file.** The workflow ran only `run_all.py`. It now runs every suite via `run_tests.py`, with a second job that installs `openpyxl` and exercises the Excel export.
- **GUI file browser opened the wrong path.** It rebuilt each file's path from the *previous* list row, so any file not first in its folder resolved to a path that did not exist.
- **MIE ran via a generated temp script.** Ticker strings were interpolated into Python source, written to the repo root, and left behind. It now takes `--tickers` / `--out` as real arguments.
- **Console coloured the risk gate's `PASS` green.** Any line containing "pass" was treated as success, so the most cautious verdict in the codebase — meaning *do not trade* — rendered as good news.
- **Excel export added** (`excel_report.py`), importing `labels/contract.py` rather than reimplementing the target, so the workbook and the codebase cannot drift on what `y` means.
- **23 new tests** (99 total, `run_tests.py`).

---

**Paper/simulation only.** No live order path exists anywhere in this repository, and nothing in this review should be read as a trading recommendation.
