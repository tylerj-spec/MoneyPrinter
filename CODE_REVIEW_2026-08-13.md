# Money Printer — code review and path to real historical testing

**Date:** 2026-08-13
**Reviewer:** Claude (adversarial review pass)
**Scope:** `claude/app/mp_v01/` and `market_intelligence_engine.py`
**Caveat:** this review is based on the file contents retrievable from the project. I have not seen every line of `_calculate_indicators`, `costs.py`, `gates/risk.py`, or `requirements.txt` in full. Items marked **[VERIFY]** need a look at the actual source before acting.

---

## 0. The headline problem

The repo now contains **two systems with opposite standards**, and the one that produces the actual picks is the one with no discipline.

| | `mp_v01/` | `market_intelligence_engine.py` |
|---|---|---|
| Point-in-time correctness | Structurally enforced (`as_of()` is the only read path) | None |
| Availability lag | Bar not usable at its own close | Uses `iloc[-1]` as if available now |
| Unknown data | Fails closed, marked `UNKNOWN` | `fillna(0)` |
| Data storage | Immutable timestamped vintages | Overwrites `AAPL_historical.csv` |
| Label definition | 5-day forward log **excess** return vs SPY | 5-day raw return > 2% |
| Costs | ~10.1% option round trip modeled | Not referenced |
| Evaluation | Permutation test, noise floor, harsh verdicts | None — emits BUY/SELL with unvalidated confidence |
| Tests | 76, run in CI | Zero, not in CI |
| News | Real-source lineage tracking | `_generate_synthetic_news()` |

`market_intelligence_engine.py` prints confident BUY signals with confidence scores. Nothing in it has ever been validated. `mp_v01/` is careful and validated and has never touched real data. **The dangerous combination is having the first one's output and the second one's reputation for rigor.**

**Recommendation:** declare `mp_v01/` the system of record. Demote `market_intelligence_engine.py` to a feature-idea scratchpad — or better, harvest its indicator math into `mp_v01/src/features/` and delete the decision layer entirely. Until that happens, its output must never be described as a "pick."

Also: the README currently advertises the news layer as "Multi-source news collection... Point-in-time aware." It is synthetic strings generated in a loop. Fix that sentence today regardless of what else you do — it's the kind of claim that, left in place, eventually gets believed by whoever reads the repo next, including future you.

---

## 1. Blocking correctness bugs

These will produce wrong results, not merely suboptimal ones. Fix before running any evaluation on real data.

### 1.1 Purge gap mixes calendar days and trading days — leakage
`src/backtest/walkforward.py`

`make_splits` builds windows with `timedelta(days=...)` and `Split.validate` checks `gap = (test_start - train_end).days >= label_horizon_days`. But `label_horizon_days=5` is **5 trading days** (per `labels/contract.py`), which is 7 calendar days — more across a holiday.

So a 5-calendar-day purge gap does **not** purge a 5-trading-day label. The last ~2 days of training labels resolve *inside* the test window. This is the exact leak the module was written to prevent, and every test currently passes because the tests use the same calendar-day assumption.

**Fix:** do the purge in **bar-index space**, not date space. Build splits over an array of trading dates and purge `label_horizon` *bars*. If you must stay in date space, convert via the actual trading calendar and add a holiday buffer. Add a regression test that constructs a split spanning Thanksgiving week and asserts it's rejected.

### 1.2 The permutation test's null is wrong for anything fitted
`src/backtest/evaluate.py`

Two separate problems:

**(a) IID shuffle vs. overlapping labels.** Labels are 5-day forward returns computed daily, so consecutive labels share 4 of 5 days and are heavily autocorrelated. `rng.shuffle(shuffled)` destroys that autocorrelation, which makes the permuted null distribution **too tight**. Too tight a null ⇒ `permutation_std` too small ⇒ `z_vs_noise` too big ⇒ p-values too small ⇒ **false `SIGNAL_CANDIDATE`**. The harness is currently biased toward finding edge, in the one place you least want that.
→ **Fix:** block permutation (or stationary bootstrap) with block length ≥ the label horizon, ideally ≥ 2×.

**(b) `predict_fn` is not refit under permutation.** The loop calls `predict_fn(feats)` inside the permutation but predictions don't depend on labels, so it's currently just wasted compute. The moment you plug in a *fitted* model, this becomes actively wrong: the null must include the fitting procedure's ability to overfit shuffled labels. Otherwise you're testing "does this fixed prediction vector beat noise" instead of "does this *procedure* beat noise," and the procedure's overfitting capacity vanishes from the null.
→ **Fix:** change the interface from `predict_fn(feats)` to `fit_predict_fn(train_X, train_y, test_X)` and refit on shuffled labels inside each permutation. Yes, it's 200× slower. That cost is the price of the number meaning what you think it means.

### 1.3 The leakage guard exists but isn't in the path
`assert_no_future_features` is defined, tested, and never called by `evaluate_walk_forward`. The harness accepts `fold_data` as bare `(features, labels)` tuples with no timestamps, so nothing can check that features respect the decision clock.

**Fix:** make the fold payload carry `decision_time` per observation and have `evaluate_walk_forward` validate internally. A guard you have to remember to call is a guard that eventually doesn't get called.

### 1.4 No train/test separation at all in the prediction engine
`market_intelligence_engine.py` → `PredictionEngine.train_model` / `.predict`

`train_model` fits on everything, `predict` runs on `.tail(1)`. There is no evaluation step anywhere — no accuracy, no holdout, no noise floor. The `confidence: 0.78` in the JSON report is a RandomForest's `predict_proba` on a model whose out-of-sample skill has never been measured. That number is currently indistinguishable from a random number in the interval.

Also: `pd.concat(all_features, ignore_index=True)` **discards the DatetimeIndex**, so you can't retrofit a time-aware split without rebuilding the whole feature path. Keep the index and add `ticker` as a column.

### 1.5 Today's bar treated as available
`market_intelligence_engine.py` uses `market_data.iloc[-1]` throughout (scoring, timing rules, prediction). `yahoo_daily.py` exists specifically to encode that a bar for date D isn't consumable until ~09:00 ET on D+1. MIE injects up to a full day of lookahead into every signal.

### 1.6 `fillna(0)` on price-level features
`PredictionEngine.predict` does `features.fillna(0)`. Those features include `SMA_20`, `SMA_50`, `SMA_200` — **dollar prices**. Filling a missing 200-day SMA with `0` tells the model "this stock's long-run average price is zero," and it will happily emit a confident prediction from that. This is the exact fail-open behavior `mp_v01` prohibits. Missing feature ⇒ abstain, not impute.

### 1.7 Two conflicting label definitions
`labels/contract.py`: binary sign of 5-trading-day forward log **excess total** return vs SPY.
`prepare_features`: `(Close.shift(-5) / Close - 1) > 0.02` — raw, absolute, thresholded.

These are not comparable. The second one is also **badly class-imbalanced** (a 5-day +2% move is maybe 25–30% of days), and MIE never reports the majority-class rate — so a model that predicts "no" every time would look ~72% accurate and nobody would notice. `mp_v01`'s `EvalReport` catches this; MIE has no equivalent.

Pick one label. It should be the `contract.py` one — excess return is what actually matters, since being long a stock that rose 2% while SPY rose 3% is not skill.

### 1.8 Synthetic news is 30% of the score
`_generate_synthetic_news()` fabricates titles, fake `news.example.com` URLs, and cycles sentiment by `i % 3`. `get_sector_sentiment` then aggregates those into a number that receives **30% weight** in `overall_score` and is printed as "🟢 Positive."

Sector sentiment is currently a deterministic function of a loop counter. Worse, in `run_analysis` every ticker is assigned `sector_sentiment.get('Technology', 0.5)` regardless of its actual sector — hardcoded.

**Fix:** set the sentiment weight to 0 and remove the component from the score until there's a real source with real `available_time`s flowing through the PIT store. A placeholder that outputs plausible numbers is more dangerous than one that outputs `UNKNOWN`.

---

## 2. Statistical issues that manufacture false edges

### 2.1 Effective sample size is much smaller than `len(X)`
Five mega-cap tech names with overlapping 5-day windows is not 5 × N independent observations. Cross-sectionally they're close to one bet on the same factor; serially the windows overlap 80%. Your true N might be ~1/20th of what the code reports.

**Fix:** report **effective N** (adjust for overlap and cross-sectional correlation) alongside raw N, and use non-overlapping decision dates for the headline result.

### 2.2 No multiple-testing accounting
Every strategy variant you try is another draw at p<0.05. Try 20, expect one "significant" result from pure noise. Nothing in the repo tracks how many have been tried.

**Fix:** a `strategy_register.jsonl` — append-only, one line per evaluated strategy, written *before* the result is seen. Apply Benjamini–Hochberg across the family. `EvalReport.verdict()` should take the family size and refuse to say `SIGNAL_CANDIDATE` without it.

### 2.3 Per-fold stability isn't reported
`EvalReport.accuracy` pools all folds, so one big fold can dominate and one lucky fold can carry the result. A strategy that's +8% in fold 3 and −1% in the other seven is noise, but pooled it may look positive.

**Fix:** report per-fold accuracy spread and require consistency (e.g. positive in ≥⅔ of folds) before `SIGNAL_CANDIDATE`. Also weight folds equally rather than by sample count for the headline number.

### 2.4 Raw price levels as ML features
`SMA_20/50/200` and `MACD` go into the RandomForest as **absolute dollars**. Tree splits become "is SMA_50 > 187.3," which is a statement about AAPL's 2025 price range, not about market structure. It won't generalize across tickers or across time.

**Fix:** ratios and z-scores only — `Close/SMA_50 - 1`, `SMA_50/SMA_200 - 1`, MACD normalized by price or by ATR, RSI is already bounded. Rule of thumb: if a feature's units are dollars, it's wrong.

### 2.5 `timing_boost` breaks calibration and double-counts
`adjusted_confidence = confidence + timing_boost`, where boost is up to ±0.23, then clipped to [0,1]. Adding a constant to a probability produces something that is no longer a probability. And the boosts key off `SMA_50`, `SMA_200`, `RSI`, and `Volume_Ratio` — **all four are already model features**, so the RandomForest has already used that information. You're adding the same signal twice.

**Fix:** delete `apply_timing_rules`, or make the rules a *filter* (veto a trade) rather than an *adjustment* to a probability. Vetoes compose safely; probability arithmetic doesn't.

### 2.6 `SELL` is a category error
The label is "5-day return > 2%." `probability[0]` is therefore P(*not* up 2%) — which includes flat, +1%, and −0.5%. Emitting `SELL` on that is claiming a downward forecast from a model that was never trained to make one.

**Fix:** either train a three-class or symmetric label, or restrict output to `BUY` / `NO_ACTION`.

### 2.7 The volatility score is close to degenerate **[VERIFY]**
`score = 50 - (volatility * 100)`. If `volatility` is annualized (as the `else` branch computes it: `std * sqrt(252)`), typical equities land at 0.20–0.35 → scores of 30 to 15, and anything above 0.50 floors at **0**. If the cached `Volatility` column is a *daily* std (~0.012), the same line gives ~48.8 for everything. The two branches appear to use different units for the same variable. Check `_calculate_indicators` and confirm.

Either way this component carries almost no information, which makes its 10% weight harmless but also pointless. Separately: "lower volatility = better" is an assumption, not a finding — and for an options *buyer* it may have the sign backwards.

### 2.8 Nobody has checked whether `overall_score` predicts anything
This is the cheapest high-value test in the whole project and it doesn't exist. The 0.4/0.3/0.2/0.1 weights and the ±15/±10/±8 adjustments are unvalidated magic numbers.

**Do this first, before any ML:** compute the walk-forward **rank information coefficient** (Spearman correlation) of each component score — technical, momentum, volatility, sentiment — against forward 5-day excess return. If `technical_score` has an IC indistinguishable from zero, then 40% of the composite is 40% of nothing, and no amount of downstream modeling fixes that. This is a few hours of work and it can kill or validate the whole scoring layer.

---

## 3. Data integrity and reproducibility

### 3.1 The cache destroys point-in-time reproducibility
MIE overwrites `data_cache/market_data/AAPL_historical.csv` on every run. `mp_v01/fetch_data.py` writes immutable timestamped vintages and never overwrites. The MIE approach means you **cannot reconstruct what the system saw last Tuesday**, which makes every historical claim unfalsifiable — and unfalsifiable is the same as worthless for this project's stated purpose.

**Fix:** MIE writes into the same vintage store, or MIE goes away.

### 3.2 yfinance `auto_adjust` conflicts with your own stated policy **[VERIFY]**
Recent yfinance defaults `auto_adjust=True`, returning split- and dividend-adjusted OHLC. `yahoo_daily.py`'s docstring explicitly refuses adjusted closes because vendors silently restate adjustment factors — the exact silent-revision class the project prohibits. MIE calls `yf.download(...)` without setting the flag, so it's probably getting adjusted data and treating it as raw.

Also: yfinance returns **MultiIndex columns** in some versions even for a single ticker, in which case `data['Close']` is a DataFrame, not a Series, and the indicator math silently produces wrong shapes rather than raising.

**Fix:** pass `auto_adjust=False` explicitly everywhere; flatten/normalize columns immediately after download and assert the expected schema; add a smoke test that fails loudly on shape change.

### 3.3 Swallowed exceptions
`ingest_stock_data` wraps everything in `except Exception` and falls back to cached data with a log line. A network failure, a schema change, and a genuine bug all look identical and all silently produce stale results that flow into predictions.

**Fix:** mark the record `STALE` with the age, and let the risk gate refuse it. Fail closed, consistent with the rest of the repo.

### 3.4 Pin dependencies **[VERIFY]**
yfinance scrapes an undocumented endpoint and breaks regularly. If `requirements.txt` is unpinned, an unattended scheduled run will one day produce silently different data. Pin exact versions; ideally hashes.

### 3.5 Hash consistency
`DataDeduplicator.get_data_hash` uses MD5; `pit/schema.py` uses SHA-256, and the V0.2 blueprint specifies SHA-256 with RFC 8785 canonical JSON. Standardize on SHA-256.

### 3.6 CI covers the wrong file
`.github/workflows/tests.yml` runs only `claude/app/mp_v01/run_all.py`. The file that produces the actual picks has **zero tests and zero CI**. That's inverted risk.

---

## 4. Missing links — what actually has to be built

These are the gaps between "76 tests pass" and "I can evaluate a strategy on real data." None of them are big; they just don't exist yet.

1. **Bars JSON → PIT store loader.** `fetch_data.py` writes `data_store/bars/*.json`. `PointInTimeStore.add()` takes `EvidenceRecord` objects. Nothing converts between them. This is the single missing piece blocking everything downstream. Include vintage selection (given a decision time, which vintage file was live?).

2. **Feature builder that reads only through `as_of()`.** Indicators computed from records available at the decision time, with `assert_no_future_features` enforced. Harvest the indicator math from MIE, drop its data path.

3. **`EvalReport` → post-cost expectancy → risk gate.** Right now `verdict()` is accuracy-based, but `gates/risk.evaluate()` wants `expected_edge_after_costs`. Nothing bridges them. Accuracy above the noise floor is meaningless if the edge is 3% and the option round trip costs 10.1% — and per your own cost model, that's the likely case. **Build this bridge early**, because it may tell you the whole options overlay is infeasible at your account size before you spend more time on signal work.

4. **Frozen prediction ledger.** Append-only JSONL, canonical JSON, SHA-256, unique on `(model_id, ticker, decision_time, horizon, input_manifest_hash)`. Per the V0.2 blueprint, which already specifies this in detail.

5. **Prediction resolver.** A separate job that scores predictions after the horizon elapses. Must be a different process from the one that makes predictions, so it can't be tempted to edit them.

6. **Scheduler.** Local Task Scheduler / cron on your machine — not GitHub Actions, since Yahoo rate-limits datacenter IPs.

---

## 5. Phased plan with exit criteria

**Phase 1 — Ingest for real.** Run `fetch_data.py` on real SPY/QQQ/MSFT over the longest free history. Build the JSON→PIT loader.
*Exit:* records in the store, `as_of()` returns sane counts at a dozen spot-checked dates, no `UNKNOWN` rate above a threshold you decide in advance.

**Phase 2 — Fix §1 bugs.** Purge in bar-index space, block permutation, refit-under-permutation, leak guard wired into the eval path.
*Exit:* `run_noise_floor.py` still reads NO_EDGE on random data **and** the planted-leak test still reads SIGNAL_CANDIDATE, with the corrected null. If the planted-leak test stops firing, you've overcorrected.

**Phase 3 — Null run on real bars.** Run a deliberately worthless strategy (coin flip, always-long, trailing momentum) on real data.
*Exit:* NO_EDGE. If a coin flip shows edge on real SPY data, the harness is still broken and nothing downstream can be trusted.

**Phase 4 — Component IC.** Rank IC of each score component vs forward excess return, walk-forward, with the strategy register active.
*Exit:* a number for each component. Most likely all near zero, and that is a **useful, honest result** that saves you money. Publish it to STATE.md either way.

**Phase 5 — Post-cost gate.** Feed any surviving signal through `costs.py` and `gates/risk.py`.
*Exit:* an `expected_edge_after_costs` figure. If negative — which is the base rate — stop and say so rather than searching for a variant that clears the bar.

**Phase 6 — Forward paper log.** Scheduled runs producing frozen, hashed predictions; separate resolver scoring them after 5 days.
*Exit:* this is the only genuinely out-of-sample evidence you will ever have. It's worth more than every backtest combined. Let it run long enough to mean something.

---

## 6. Pre-register this before real money

Write these numbers down **now**, before you have results, and put them in STATE.md. Deciding the bar after seeing the data is how everyone talks themselves into a losing system.

- Minimum forward paper predictions before any real capital: **≥ 200 non-overlapping decisions** (~4 years of weekly decisions on 3 tickers — this is the uncomfortable one, and it's the honest one).
- Required post-cost expectancy, stated as a number.
- Required calibration: predicted 70% buckets must resolve within a stated band of 70%.
- Maximum acceptable paper drawdown.
- **Any change to the strategy resets the clock.** No exceptions, no "it was only a small tweak." This rule is the entire defense against fitting the forward test.
- A written statement of what result would make you abandon the project. If there isn't one, the project can't fail, which means it can't succeed either.

---

## 7. Quick wins (< 1 hour each)

- Fix the README's "Point-in-time aware" claim about the synthetic news layer.
- Set the sentiment weight to 0 until the source is real.
- `auto_adjust=False` on every `yf.download` call.
- Replace `fillna(0)` with an abstain path.
- Pin `requirements.txt`.
- Add `market_intelligence_engine.py` to CI with at least an import-and-smoke test.
- Add `data_cache/` to `.gitignore` if it isn't already covered.
- Fix the hardcoded `sector_sentiment.get('Technology', 0.5)` for all tickers.
