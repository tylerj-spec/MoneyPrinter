# Data Provider Recommendation — decision-ready

Researched 2026-08-12 with verified current pricing. This supersedes the provisional guidance in `DATA_SOURCING_ANALYSIS.md`.

You said: willing to spend, gradually, and you don't want to sink a lot of money into building the thing that's supposed to make money. That constraint shapes this entire recommendation.

---

## The recommendation, in one line

**Start with Polygon/Massive Starter at $29/month, plus the free Cboe historical trial. Total first-month spend: $29.** Don't buy anything else until the pipeline is proven end to end.

---

## Verified pricing

**Polygon.io** (rebranded to Massive in late 2025; options product carried over). Billed per asset class — options is a separate subscription from stocks.

| Tier | Price | History | Notes |
|---|---|---|---|
| Starter | **$29/mo** | **2 years** | 15-minute delayed |
| Developer | **$79/mo** | **4 years** | Second-level aggregates |
| Advanced | **$199/mo** | Tick-level | Real-time Greeks & IV |

**Cboe DataShop** — the authoritative exchange source.

| Product | Price |
|---|---|
| EOD Open-Close subscription | $500/mo |
| EOD ad-hoc historical request | $400 per request (covers any number of months back to Jan 2018) |
| Academic rate | $750/year |
| **Free trial** | **Up to 6 months of EOD Open-Close historical data**, for anyone who hasn't previously purchased or trialed it |

**EODHD** — history only reaches Q4 2023 (~2.5 years). Now clearly beaten by Polygon Developer on history depth at a comparable price. Drop from consideration.

---

## Why Starter at $29, specifically

**The 15-minute delay costs you nothing.** Your approved decision clock is 15:45 ET with a 5-trading-day hold. You are not trading intraday. Delayed data is functionally identical to real-time for this design. The $199 Advanced tier buys real-time data you have no use for — that's $170/month of pure waste at your stage.

**Two years of history is enough to build and validate the pipeline.** You cannot demonstrate alpha yet regardless of data depth, because there is no strategy. What you need first is to prove the ingestion, point-in-time store, labeling, and backtest harness all work correctly against real data. Two years is plenty for that.

**Grab the Cboe free trial in parallel.** Six months of authoritative exchange EOD data at zero cost, and it doubles as a cross-check — if Polygon and Cboe disagree on the same contract on the same day, you've found a data quality problem you'd otherwise never see. That validation is worth more than the extra history.

---

## The upgrade decision, and when to make it

**The regime-coverage problem is real but not yet binding.** Two years of history covers 2024–2026, which is broadly one regime. Your own rules require robustness across regimes, so at some point you need more depth. Polygon Developer at $79/mo reaches back four years to ~2022, which captures the 2022 bear market — a genuinely different regime.

**But don't buy it yet.** Upgrade only when you have a candidate strategy that shows promise on two years and you need to know whether it survives a different regime. Buying regime depth before you have anything to test against it is spending money on optionality you can't exercise.

**Trigger to upgrade:** a strategy passes walk-forward on 2024–2026 with positive post-cost expectancy. Then $79/mo to see if it holds in 2022. Not before.

---

## What to avoid, with reasons

| Don't buy | Why |
|---|---|
| Cboe $500/mo subscription | 17x the cost of Polygon Starter for data you can largely get free via the trial at this stage |
| Polygon Advanced $199/mo | Real-time data for a system that decides once daily and holds five days |
| OptionMetrics / IvyDB | Institutional pricing, institutional use case. Not remotely justified |
| CRSP / WRDS | Already deferred. Unnecessary for three non-delisting instruments |
| Any hardware | Nothing has hit a compute or storage bottleneck. 100 GB is far more than three instruments need |

---

## Realistic spend trajectory

| Phase | Monthly | Cumulative | Trigger to advance |
|---|---|---|---|
| Pipeline validation | $29 | $29–87 | Ingestion + PIT store + backtest working on real data |
| Strategy search | $29 | ~$150 | A candidate with positive post-cost expectancy |
| Regime robustness | $79 | ~$400 | That candidate needs out-of-regime validation |
| Paper trading | $79 | ~$700 | Months of forward paper results before any real capital |

**Realistic total before you'd fund the $1,000 Robinhood account: roughly $400–700 over six-plus months.**

Worth saying plainly: that's a meaningful fraction of the capital you plan to trade with. At $29/month you'd spend $348/year on data to trade a $1,000 account — the data costs a third of the account annually. That math only works if the account grows substantially, or if you're treating this as building a system whose value is the system itself rather than the returns on the first $1,000. Both are legitimate motivations. It's worth being clear with yourself about which one you're in it for, because it changes what "worth it" means.

---

## Actions

1. Sign up for **Polygon/Massive Starter, $29/mo, options asset class**. Verify at massive.com/pricing before paying — pricing was rebranded and may have shifted.
2. Request the **Cboe DataShop free trial** for EOD Open-Close historical data.
3. Report back: earliest available date for SPY, QQQ, MSFT chains; whether bid/ask is included or last-trade only; rate limits on your tier.

Item 3 matters most. Last-trade-only pricing would make realistic fill modeling impossible, and that would change the recommendation entirely.

Sources: [Polygon pricing analysis](https://apis.io/plans/polygon-io/polygon-io-plans-pricing/) · [Options data pricing comparison](https://flashalpha.com/articles/options-data-pricing-comparison-flashalpha-thetadata-polygon-spotgamma-squeezemetrics) · [Cboe Option EOD Summary](https://datashop.cboe.com/option-eod-summary) · [Cboe fee schedule filing](https://www.federalregister.gov/documents/2024/01/18/2024-00848/self-regulatory-organizations-cboe-exchange-inc-notice-of-filing-and-immediate-effectiveness-of-a)
