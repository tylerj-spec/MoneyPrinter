# MoneyPrinter validation standard

MoneyPrinter is a paper/simulation research application. A passing test suite or a strong
historical result is not evidence that a live account will achieve the same result. The
validation process is intentionally designed to make optimistic mistakes difficult.

## Point-in-time data is non-negotiable

A decision may consume a record only when its **availability timestamp** is at or before the
decision cutoff. Event dates, fiscal periods, quote observation times and today's reconstructed
history are not substitutes for historical availability. Revisions remain separate vintages.
Current connector snapshots may be archived for forward research, but they are never silently
backdated into a historical replay.

Train/test splits use exchange sessions, a purge at least as long as the label horizon, and an
embargo. Grouped permutation keeps observations from the same decision date together. Any
ambiguous chronology should fail closed rather than fall back to calendar-day arithmetic.

## Execution results use observed markets, not model prices

A historical option decision and its later outcome are separate. A decision-time quote cannot
fill the order it helped create. Simulated execution requires a new post-submission quote after
the configured latency, a marketable limit, verified contract-size units, sufficient displayed
size, an eligible non-delayed feed, and a known exchange session. Long entries pay the observed
ask; long exits receive the observed bid; fees are deducted separately. Missing quotes become
`NO_ENTRY_FILL` or `UNRESOLVED`, never a modelled price or zero return.

One-contract replay does not claim to model market impact or queue position. Those limitations
must remain visible when historical or paper results are reviewed.

## Modelled values stay labelled as modelled

Implied volatility and Greeks are model outputs, not observations. The current Greek engine is
a European Black-Scholes approximation and is not an American-option valuation guarantee.
Model assumptions belong in the frozen record so future refinements can be compared without
silently rewriting what the model knew at the time.

## Backtests must try to disprove the strategy

Evaluation is chronological and walk-forward. The noise floor refits the learner under
block-permuted labels, rather than permuting labels around a model that was fit once. Synthetic
random-walk tests must read `NO_EDGE`/`INCONCLUSIVE`, while planted-signal tests must be capable
of detecting a relationship that is genuinely present.

Testing many strategies and reporting only the winner is a form of backtest overfitting. Bailey,
Borwein, Lopez de Prado and Zhu's *The Probability of Backtest Overfitting* is the reference for
why ordinary holdout results alone are insufficient. Strategy variants and experiment identities
therefore remain separate and active weights are never rewritten automatically from a backtest.

## Promotion sequence before real money

No accuracy percentage automatically unlocks live trading. The intended sequence is:

1. deterministic unit, adversarial and synthetic-noise tests;
2. timestamp-verified historical quote replay with realistic bid/ask execution;
3. untouched out-of-sample / forward holdout evaluation;
4. persistent forward paper trading, including reconciliation against broker paper fills;
5. stability checks across market regimes, tickers, spreads and missing-data cases;
6. manual review of expectancy after costs, uncertainty, drawdown, concentration and data quality;
7. only then, if the owner independently chooses, a separately designed live-money risk process.

The CFTC's hypothetical-performance guidance is a useful reminder of the core limitation:
simulated results do not represent actual trading and can differ materially because of liquidity
and hindsight. MoneyPrinter should preserve that distinction in every dashboard and report.

## Regression bar

A change is review-ready only when the complete offline suite finishes within bounded per-step
timeouts on supported Linux and Windows CI jobs. Required regressions include future-data
mutation invariance, stale/future/crossed quote rejection, no-fill and partial-fill behavior,
displayed-liquidity consumption, ledger restart/integrity, invalid numeric domains, grouped-date
permutation, connector provenance, GUI credential handling and deterministic reproduction of
frozen decisions.
