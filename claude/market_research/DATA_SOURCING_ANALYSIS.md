# Data Sourcing Analysis

Produced 2026-08-12 for the Money Printer project. Written directly rather than via the specialists — SPEC-ROUND-004 and 005 went unanswered (the Slack app appears to have hit a rate limit after four rounds), so this is my own analysis with sources cited. It should be re-reviewed by the specialists when they're responsive.

---

## The finding that changes the plan

**Almost none of your alt-data sources can be honestly backtested. They can only be paper-forwarded.**

Your own rule is that a historical simulation may access only information publicly available at the simulated decision timestamp. For social data this is close to impossible to satisfy retroactively:

- WSB posts get **deleted** (by authors, mods, and automod). A historical archive contains survivors, which is survivorship bias in its purest form — you'd be studying the posts that were allowed to remain.
- Posts get **edited** with no public revision history.
- **Vote counts mutate continuously.** A post at 200 upvotes when you'd have seen it at 15:45 may show 40,000 in an archive. Any feature keyed on score is contaminated.
- Deleted tweets are unrecoverable.

So a backtest over archived social data measures something that never existed at decision time. It will look better than reality, and you will not be able to tell by how much.

**The honest path:** start capturing timestamped snapshots yourself now, forward-only. Each snapshot records what the source showed at a specific `available_time`, immutably. In roughly 3–6 months you'd have a small but genuinely point-in-time alt-data set. That's slow, and it's the only version that isn't self-deception. Meanwhile, validate the pipeline on market data, which *can* be replayed honestly.

This isn't a reason to drop alt data. It's a reason to sequence it: market data validates the machinery now, alt data accumulates in parallel and gets evaluated later.

---

## Source-by-source

### Congressional trading disclosures — **ADOPT.** Best source on your list.

Legally clean (STOCK Act filings are public record), free, and — uniquely among your candidates — **honestly replayable.** Each filing has a real, immutable filing timestamp, so `available_time` is well-defined and the record doesn't mutate afterward.

The catch is structural: disclosure is required within 45 days of the trade, so the information is stale by construction. Any edge is in the *disclosure* event, not the trade. That's a legitimate thing to model, but don't expect to front-run the transaction — you're modeling market reaction to a late public filing.

Sources: House and Senate financial disclosure portals directly (free, authoritative, awkward formats), or free aggregators for convenience. Prefer the primary filings for lineage integrity; use aggregators only as an index. Storage: negligible, well under 1 GB.

### WallStreetBets — **CONDITIONAL.** Forward-capture only.

Reddit's Data API is **free for non-commercial use within 100 queries/minute per OAuth client**, covering personal projects and academic research. Commercial use requires approval at **$0.24 per 1,000 calls**, with a high-volume tier around **$12,000/month for 50M calls**. ([Reddit API pricing 2026](https://www.techloy.com/reddit-api-pricing-in-2026-complete-guide-for-developers-and-businesses/), [SocialCrawl](https://www.socialcrawl.dev/blog/reddit-data-api-2026))

Whether a personal trading research system counts as "non-commercial" is genuinely ambiguous — you're not selling anything, but you intend to profit. Worth reading the current terms before relying on the free tier. Mark this **UNKNOWN** until confirmed; don't build a dependency on an interpretation that could be wrong.

**Pushshift, the archive everyone used for historical Reddit research, lost API access.** The current alternative is Project Arctic Shift (monthly dumps, limited query API). But note this doesn't solve the PIT problem above — a dump still contains only surviving posts with final vote counts.

Also worth saying plainly: WSB sentiment is one of the most heavily studied retail signals in existence. If a simple version worked, it would be arbitraged. Treat it as a low-prior candidate that must earn its place, not as a centerpiece.

Storage forward-capture: modest, a few GB/year for one subreddit with snapshots.

### X / Twitter accounts — **REJECT for now.** Revisit later.

Three separate problems, any one of which is disqualifying today:

1. **Grok cannot be used as a data pipe.** Grok's live X access is an interactive subscription feature. Using it to bulk-extract, store, and redistribute X content into your own database is a different thing from asking it questions, and likely violates terms. I'd want that verified explicitly before building on it. Using Grok as an *analyst* that reads and reasons is fine; using it as an *ingestion layer* is not the same thing.
2. **X API pricing** for meaningful volume has historically been steep. Mark UNKNOWN — verify current tiers before assuming.
3. **Worst PIT reconstructability of any source here.** Deletions are permanent and invisible.

Not permanently off the table, but it's the highest cost and lowest replay integrity on the list. Last thing to add, not first.

### Market news — **CONDITIONAL on license terms.**

The binding constraint is almost never availability, it's **redistribution and storage rights.** Most commercial news APIs prohibit retaining full article text. Headlines, timestamps, URLs, and derived features are usually permissible; full-text corpora usually aren't.

Practical approach: store headline + `published_time` + `available_time` + source + canonical URL + your own derived features, and don't retain full bodies unless the license explicitly allows it. That also happens to be far cheaper on storage.

SEC EDGAR is free, authoritative, timestamped, and has none of these problems. It should be the backbone of the text layer, with news as a supplement.

---

## Historical options data — the real bottleneck, now priced

This has been the project's top risk since V0.1. Verified options:

| Provider | Notes |
|---|---|
| [EODHD](https://eodhd.com/lp/us-stock-options-api) | Full contract detail: OHLC, bid/ask, volume, OI with day-over-day change, all five Greeks, IV. **History only extends to Q4 2023** (~2.5 years). ~6,000 underlyings. |
| [HistoricalData.net](https://historicaldata.net/options.html) | EOD chains, Greeks, IV. ~$59/month, 7-day trial. |
| [Cboe DataShop](https://datashop.cboe.com/option-eod-summary) | Authoritative exchange source. OHLC, volume, VWAP, OI, plus IV/Greeks calculations. À la carte. |
| [Polygon.io](https://polygon.io) / [Intrinio](https://intrinio.com/options/eod-historical-options) | Tiered; Polygon has a free tier. |
| OptionMetrics (IvyDB) | Institutional gold standard, deepest history. Custom pricing, expensive. |

**The constraint that matters: EODHD's options history starts Q4 2023.** That's roughly 2.5 years — which means your backtest window contains no 2022 bear market, no 2020 COVID vol shock, no 2018 Volmageddon. You would be fitting and validating entirely within one broad regime. Your own instructions require robustness across regimes; a 2.5-year window cannot deliver that.

So the honest choices are: accept a regime-limited backtest and lean much harder on forward paper trading, or pay for deeper history (Cboe DataShop à la carte for specific years, or OptionMetrics). Given three instruments in the first slice, buying targeted Cboe history for SPY/QQQ/MSFT across 2018–2023 is plausibly affordable and would cover multiple regimes. **That's the single highest-value purchase on the table** — and it's consistent with your stated preference to spend on data validity before hardware.

Recommendation: start with a cheap EOD source ($59/mo tier or Polygon free) to build and test the pipeline, then buy targeted historical depth once the machinery is proven. Don't buy depth before you can use it.

---

## Storage plan against ~100 GB

| Layer | Allocation | Notes |
|---|---|---|
| Daily equity bars, full US market, decades | 2–5 GB | Trivially fits |
| EOD options chains, 3 underlyings, multi-year | 5–20 GB | Comfortable |
| EOD options chains, ~6,000 underlyings | 40–80+ GB | Fits, but crowds everything else |
| SEC filings text (targeted) | 5–15 GB | |
| News metadata + derived features | 1–5 GB | Headlines only, no full text |
| Social forward-capture snapshots | 2–10 GB/yr | |
| Derived features, manifests, frozen predictions | 5–10 GB | Grows with every run |

**Full-chain intraday options history is not feasible in 100 GB.** That's a terabyte-scale dataset for even a modest underlying set. EOD chains for a focused universe are the right target. Given the approved first slice is three instruments, storage is comfortably a non-issue — **don't buy a drive, and don't let storage drive any decision.**

---

## Ratings schema — proposal

You asked for standardized ratings on meaningful variables. The danger with any rating scheme is that it becomes an unearned confidence multiplier: a number that feels rigorous, propagates into sizing, and was never validated. Guard rails matter more than the scale.

Proposed dimensions, each 0–4 with **concrete anchors** rather than vibes:

- **Source reliability** — 4: primary filing/exchange. 3: wire service. 2: established secondary press. 1: unvetted aggregator. 0: anonymous social.
- **Independence** — derived mechanically from `lineage_cluster_id`, never asserted by a model. Syndicated copies collapse to one.
- **Novelty** — is this new information at `available_time`, or a restatement of something already in the store?
- **Specificity** — 4: quantified, dated, checkable. 0: vague directional sentiment.
- **Recency** — decay function on `available_time` relative to decision time.

Three rules that keep it honest:

1. **Ratings gate, they don't amplify.** A rating may *disqualify* evidence from counting. It may never increase position size. Sizing comes from the deterministic risk layer only.
2. **Combination is conservative, not additive.** Use the minimum or a capped aggregate, not a sum — otherwise ten mediocre sources manufacture false confidence.
3. **Every rating is stored with the prediction and frozen.** A rating that can be retroactively adjusted is an audit-trail hole.

Critically: these weights are **starting defaults, not proven parameters.** They must be validated against outcomes before they influence anything real. Until then they're structured guesses, and should be labeled as such wherever they appear.

---

## What I'd sequence next

1. Wire a free/cheap EOD equity source for SPY/QQQ/MSFT into the existing point-in-time store, with real availability timestamps
2. Implement the approved label contract (5-day forward log excess return vs. SPY, 15:45 ET decision clock)
3. Run the existing walk-forward harness against a trivial baseline — establish what "no edge" looks like before trying to beat it
4. Start forward-capture of congressional disclosures (cheapest honest alt-data win)
5. Only then price deeper options history against a proven pipeline

Sources: [EODHD](https://eodhd.com/lp/us-stock-options-api) · [HistoricalData.net](https://historicaldata.net/options.html) · [Cboe DataShop](https://datashop.cboe.com/option-eod-summary) · [Intrinio](https://intrinio.com/options/eod-historical-options) · [Reddit API pricing](https://www.techloy.com/reddit-api-pricing-in-2026-complete-guide-for-developers-and-businesses/) · [SocialCrawl on Reddit API](https://www.socialcrawl.dev/blog/reddit-data-api-2026)
