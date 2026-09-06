# MoneyPrinter data-source roadmap

This is an engineering backlog, not a claim that any vendor makes the strategy profitable.
Every connector must record source, observation timestamp, received timestamp, and the
availability rule used in historical replay. Unknown or delayed data must fail closed.

## Free / free-tier sources to integrate first

1. **SEC EDGAR** — filings and XBRL company facts. Use filing acceptance/availability time,
   never fiscal-period end, as the historical cutoff. No API key is required for the public
   submissions/companyfacts APIs. Cache politely and identify the client per SEC guidance.
2. **FRED + ALFRED** — macro series and historical vintages. ALFRED vintages are preferred
   for backtests because revised macro values must not leak backward in time.
3. **BLS release calendar/data** — macro event-risk flags and official releases. Archive the
   observed schedule/vintage rather than reconstructing it from today's calendar.
4. **Federal Reserve** — FOMC meeting/calendar/statement timestamps and official releases.
5. **Massive free/current entitlement** — keep the existing diagnostic and use only endpoints
   the key demonstrably supports. End-of-day/minute aggregates are not substitutes for
   timestamped executable option bid/ask quotes.
6. **Broker/free-tier forward feeds** — candidates include Tradier and Alpaca. Treat delayed,
   indicative, sandbox, or non-OPRA quotes as such. They may be useful for development and
   forward collection but must not be mislabeled as executable historical NBBO.

## Paid candidates — future evaluation note

Do not purchase these merely because they are listed. Before subscribing, run a small vendor
acceptance test covering normal sessions, an early close, missing data, an adjusted contract,
quote timestamps/sizes, and several historical dates.

- **ThetaData** — candidate for deeper historical option quote/NBBO research.
- **Massive paid options tiers** — attractive if the existing adapter can be reused and the
  required historical quote endpoints are included in the chosen entitlement.
- **ORATS** — candidate for long-history option analytics/data; carefully respect snapshot
  publication time relative to MoneyPrinter's decision timestamp.
- **Alpaca paid market data** — candidate for consolidated forward market data and paper
  brokerage integration; keep broker simulation limitations separate from our own fill model.

## Data we should prefer before noisy alternative inputs

Timestamped option bid/ask and size; synchronized underlying bid/ask; contract reference and
corporate-action deliverables; open-interest observation date; IV/skew/term structure;
earnings/ex-dividend calendars; exchange sessions/early closes; risk-free-rate vintage; and
verified commissions/fees.

Social media, political-trading feeds, unusual-options-activity products, and additional LLM
agents should remain experimental until the core quote/execution/label loop demonstrates that
an added feature improves untouched out-of-sample results.
