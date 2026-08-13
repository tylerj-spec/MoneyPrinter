# Money Printer — Project Plan

## Goal
Build and paper-trade an automated stocks/options trading bot. No live orders or real money movement are placed by any AI agent — all execution stays paper-trading until Tyler manually decides to go live.

## Broker/venue
Alpaca (paper trading API). Free, well-documented, supports stocks and options, and has a first-class paper account that mirrors the live API without touching real funds.

## Architecture
1. **Data layer** — pull historical + live market data (Alpaca Market Data API).
2. **Strategy layer** — pluggable strategy modules (start with one simple, explainable strategy, e.g. moving-average crossover or mean reversion).
3. **Backtest engine** — run strategies against historical data, report P&L, drawdown, Sharpe.
4. **Execution layer (paper only)** — submits orders to Alpaca's paper endpoint. Live endpoint is not wired up.
5. **Risk/config layer** — position sizing limits, max drawdown kill-switch, all in a single config file.
6. **Logging/reporting** — trade log, daily summary, sent to Slack channel.

## Milestones
1. Repo scaffold + config (this session)
2. Data ingestion + one backtested strategy
3. Backtest report reviewed by Tyler
4. Paper execution loop running on a schedule
5. Ongoing monitoring reports posted to Slack

## Task breakdown for Slack agents
- **Agent: Data** — implement Alpaca market data pull, historical + live bars.
- **Agent: Strategy** — implement + backtest first strategy (MA crossover baseline).
- **Agent: Execution** — build paper-order submission wrapper with risk limits/kill-switch.
- **Agent: Reporting** — daily P&L summary posted back to Slack channel.

## Guardrails
- Paper trading only until Tyler explicitly approves going live.
- No agent should hold or transmit real brokerage API keys with live-trading scope.
- All order logic must be reviewed before any live-mode toggle is added.
