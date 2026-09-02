# Money Printer — follow-up code review

**Date:** 2026-09-02
**Reviewer:** Claude (adversarial review pass, second)
**Scope:** whole repository at commit `af1a059` — 4,595 lines of Python
**Prior review:** `CODE_REVIEW_2026-08-13.md`
**Method:** all eleven findings below were reproduced by executing code, and each carries the actual output. **3.1** was resolved on 2026-09-02 by a live fetch on Tyler's machine after the review environment's network policy blocked Yahoo; the assumption it questioned holds, and the finding is downgraded rather than closed — see below.

---

## 0. Headline

The 2026-08-13 review was accurate. Three weeks later, its three blocking findings are **still live in `main`** (§2 below). That is the single most important fact in this document: the problem is not that these defects are unknown, it is that knowing about them has not yet changed the code.

Three further defects were found that the prior review did not cover (§1). All three sit in `mp_v01/` — the system of record, the careful one — and all three fail in the same direction: **toward more apparent evidence, more apparent data, and fewer refusals.** That is the expensive direction for a project whose stated default is abstention.

One new detail sharpens §1.1 of the prior review considerably: **the test suite certifies the bug.** See §2.1.

---

## 1. New blocking bugs

Not covered by the 2026-08-13 review. All three are in `claude/app/mp_v01/`.

### 1.1 Two revisions of one record both survive `as_of()`
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

**Fix:** make `_superseded_by` hold a set and skip a record if *any* superseding revision is available at `t`; or reject a second supersession of an already-superseded record at `add()` time. The second is more in keeping with the rest of the module, which prefers loud rejection over quiet accommodation. Add a regression test with a three-vintage chain and a two-revisions-of-one-original case.

### 1.2 An assumed −100% delisting return is labelled `OK` and marked usable
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

**Fix:** either return a distinct status so the imputation is filterable, or have `is_usable()` consult `delisting_return_imputed`. The second is a one-line change and matches the module's existing posture.

### 1.3 The risk gate raises instead of failing closed
`src/gates/risk.py` — `need()` and the threshold comparisons

`need()` handles `None` and NaN carefully — the NaN guard is genuinely good, with a comment explaining that an unguarded NaN slides past every threshold, and there is a test for it. It does **not** handle a value of the wrong type.

A candidate arriving from JSON, a model response, or a spreadsheet with `"35"` instead of `35` reaches `limits.min_dte <= dte` and raises.

The module's whole premise is that it is the last deterministic thing between a model's proposal and a decision. **An exception is not a decision.** Whatever calls it either crashes or catches broadly, and a broad catch around the risk gate is how `PASS` quietly becomes "skipped".

**Reproduced:**

```
candidate = dict(..., dte="35", ...)   # everything else valid

RAISED TypeError: '<=' not supported between instances of 'int' and 'str'
```

**Fix:** extend `need()` to reject non-numerics the way it rejects NaN — append `invalid_type:{key}` to `failed`, which already routes to `PASS`. Roughly four lines, and it closes the last hole in an otherwise well-built gate.

---

## 2. Previously identified, still live in `main`

These restate the 2026-08-13 review. They are repeated here with reproductions because a reproduction is more actionable than a description, and because three weeks have passed.

### 2.1 Purge gap counts calendar days — and the test certifies the bug
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

**Fix:** as the prior review prescribes — purge in bar-index space. But write the Thanksgiving-week regression test **first** and watch `purge_gap_prevents_label_horizon_bleed` fail alongside it. That existing test is part of the defect and must be rewritten, not preserved.

### 2.2 The permutation null never refits
`src/backtest/evaluate.py` — see prior review §1.2(b)

`predict_fn(feats)` sits inside the permutation loop but takes no labels, so it returns the identical prediction vector on all 200 iterations.

Today this is only wasted compute, which is precisely why it is dangerous: the noise floor still reads `NO_EDGE` on random data, so the harness looks trustworthy. It stops being harmless the moment a fitted model is plugged in — the null must include the fitting procedure's capacity to overfit shuffled labels.

**Reproduced — instrumented probe, 4 folds, 50 permutations:**

```
predict_fn calls: 204   (4 scoring + 4×50 permutation)
distinct feature inputs ever passed: 1
```

**Fix:** as prescribed — change the interface to `fit_predict_fn(train_X, train_y, test_X)` and refit inside each permutation. This is the highest-leverage fix in the repository, because it is the instrument every later result is read on. Phase 4's component rank IC means nothing until the null is right.

### 2.3 The leakage guard is still not in the path
`src/backtest/walkforward.py` — see prior review §1.3

`assert_no_future_features` remains defined, tested, and never called by `evaluate_walk_forward`. Confirmed unchanged.

---

## 3. Medium and low severity

### 3.1 Split adjustment was an undocumented assumption — now verified, still untested
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

**Remaining fix — a judgment call, deliberately not made unilaterally.** Two options, with a real tradeoff:

- **Magnitude threshold** in `normalize_bars`: flag any single-day move beyond some bound as `UNKNOWN`. Simple, offline-testable, but blunt — a genuine −40% earnings collapse is a real observation and marking it `UNKNOWN` silently deletes exactly the tail events that matter most to a risk model.
- **Split cross-check**: fetch `yf.Ticker(t).splits` alongside the dividends this adapter already fetches, and assert no return straddling a split date matches the unadjusted price ratio. Precise, no false positives on real crashes, but it lives in the live-fetch path and cannot be tested offline.

The second is better and is what the hazard actually calls for. It needs a decision about where the threshold sits and a machine with network access to develop against.

### 3.2 `src/strategy/` is an empty package
`src/strategy/__init__.py` — 0 lines

Every other package under `src/` is substantive. This one is empty, and roadmap Phases 3 through 5 — null run on real bars, component rank IC, post-cost gate — all assume something lives here to be evaluated. The pipeline can measure a strategy but has nowhere to define one, which is why the demos pass functions inline.

Not a bug. Named because it is the actual blocker between "the machinery is verified" and "Phase 3 can start", and an empty directory appears on no status report.

### 3.3 Dead branch: both confidence thresholds return `BUY`
`market_intelligence_engine.py` — `PredictionEngine.predict()`

```python
if probability[1] > 0.65:
    signal = 'BUY'
elif probability[1] > 0.55:
    signal = 'BUY'
```

The arms are identical, so the 0.65 threshold does nothing and the rule is simply `BUY if p > 0.55`. Residue from the prior review's §2.6 fix that removed `SELL`. Harmless, but it reads as graded confidence and is not.

On the same lines, `prediction = self.model.predict(features)[0]` is computed and discarded.

### 3.4 Six unused imports, three of them heavy
`market_intelligence_engine.py` lines 18–31

`os`, `sys`, `Path`, `requests`, `BeautifulSoup` and `StandardScaler` are imported and never used. The last three matter: the module cannot be imported without `requests`, `beautifulsoup4` and `scikit-learn` installed, and uses none of them. `bs4` is a leftover from before the scraper became synthetic.

### 3.5 The two requirements files contradict each other on `yfinance`

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

1. **Fix the null first (§2.2).** Every result the project will ever produce is read on this instrument. Nothing downstream means anything until it is calibrated.
2. **Write the failing purge test, then fix the purge (§2.1).** Construct a split spanning Thanksgiving week and assert it is rejected. It will fail, and so will the existing `purge_gap_prevents_label_horizon_bleed`. Do not fix the code first — you want to see both tests fail.
3. **Close the three fail-closed holes (§1.1, §1.2, §1.3).** A set instead of a dict in the store, `is_usable()` consulting the imputation flag, a type check in `need()`. Small, independent, each with an obvious regression test.
4. **Decide the split guard (§3.1).** The assumption is verified and documented; what remains is choosing between a magnitude threshold and a split cross-check, and pinning `yfinance` to the version that actually fetched (§3.5).
5. **Then start Phase 3.** Running a deliberately worthless strategy on real bars before step 1 would tell you nothing — a null that cannot price overfitting cannot certify a null result either.

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
