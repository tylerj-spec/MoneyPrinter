# Money Printer

An AI-agent-coordinated market-intelligence and options-research project. Built by a human (Tyler) directing a small team of AI agents — Claude, ChatGPT/Codex, and several Slack-based specialists.

**Paper/simulation only.** No live trading, no broker execution, no moving money, anywhere in this repository. There is no code path anywhere in this codebase that emits a live order.

## Status

76 tests passing in `claude/app/mp_v01/`. Zero external dependencies on Linux/macOS; on Windows, `pip install tzdata` is needed once.

**NEW**: Market Intelligence Engine with incremental data ingestion and automatic deduplication.

## Why this exists

The goal is to find out, honestly, whether a small, disciplined, point-in-time-correct research pipeline can identify a real statistical edge in equities/options — and to do it in a way that's structurally sound and reproducible.

## Hard constraints

- Paper/simulation only. No live orders, no broker execution, no moving money.
- No fabricated facts, prices, or citations. Unknown values are marked `UNKNOWN`, never guessed.
- Code is never claimed to work without actually being run.
- Abstention (`PASS`) is the default and preferred outcome over a confident guess.
- Credentials live in environment variables only — never in files, logs, or chat.

## Layout

```
├── market_intelligence_engine.py  Market data ingestion, news scraping, predictions
├── requirements.txt               Python dependencies
├── gui.py                         Desktop GUI - run tests, fetch data, browse results
├── claude/                        Claude's work: architecture, orchestration, review
│   ├── app/mp_v01/                The core codebase
│   ├── market_research/           Data source licensing analysis
│   ├── reports/                   Architecture blueprints, agent design docs
│   └── scheduled_state/           STATE.md — single source of truth
├── codex/                         Codex's workspace (local execution, ingestion)
└── shared/                        Cross-agent data handoffs
```

## Market Intelligence Engine

A comprehensive system for financial data analysis, news aggregation, and predictive trading signals.

### Features

1. **Historical Market Data Ingestion** (1-year lookback)
   - Automatic incremental updates (only fetches new data)
   - Deduplication logic prevents duplicate records
   - 20+ technical indicators calculated
   - CSV export for archival

2. **Sector News Scraping & Aggregation**
   - Multi-source news collection
   - Sector classification via keywords
   - Sentiment scoring by sector
   - Point-in-time aware

3. **Unified Scoring System**
   - Technical Score (40%): Trends, MAs, momentum
   - Momentum Score (20%): Short/medium-term moves
   - Volatility Score (10%): Risk-adjusted metrics
   - Sentiment Score (30%): News & market sentiment
   - Overall Score (0-100 scale)

4. **ML-Based Predictions with Timing Rules**
   - Random Forest classifier on historical patterns
   - 5-day price movement prediction
   - Timing rules for trend confirmation, volume, RSI
   - Confidence-adjusted signals: STRONG, MODERATE, WEAK

### Quick Start

#### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# On Windows, if timezone errors:
pip install tzdata
```

#### Basic Usage

```python
from market_intelligence_engine import MarketIntelligenceApp

app = MarketIntelligenceApp()

tickers = ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'TSLA']
sector_etfs = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Finance': 'XLF'
}

# Run analysis (incremental data update on subsequent runs)
results = app.run_analysis(tickers, sector_etfs)

# Generate report and summary
app.generate_report('market_intelligence_report.json')
app.print_summary()
```

#### Run as Script

```bash
python market_intelligence_engine.py
```

### Data Management

#### Incremental Updates

The engine automatically manages data to avoid reprocessing:

```python
from market_intelligence_engine import HistoricalDataIngester

ingester = HistoricalDataIngester(lookback_years=1)

# First run: downloads full 1-year history
data = ingester.ingest_stock_data('AAPL')

# Subsequent runs: only fetches new data since last update
data = ingester.ingest_stock_data('AAPL')

# Export to CSV backup
ingester.export_to_csv('market_data')
```

#### Deduplication

Built-in deduplication ensures:
- No duplicate OHLCV records per date
- Automatic merging of new data with existing cache
- Verification of data integrity on load

```python
# Cache location (automatic)
data_cache/
├── market_data/
│   ├── AAPL_historical.csv
│   ├── MSFT_historical.csv
│   └── ...
└── timestamps.json  # Tracks last update for each ticker
```

#### Manual Cache Management

```python
import shutil

# Clear entire cache and start fresh
shutil.rmtree('data_cache', ignore_errors=True)
app.run_analysis(tickers, sector_etfs)  # Downloads fresh data
```

### Output

#### JSON Report

```json
{
  "timestamp": "2026-08-13T15:35:00",
  "market_data_summary": {
    "AAPL": {
      "latest_close": 195.50,
      "period_high": 205.75,
      "period_low": 150.25,
      "records": 252
    }
  },
  "unified_scores": [
    {
      "ticker": "AAPL",
      "overall_score": 67.44,
      "technical_score": 72.5,
      "momentum_score": 65.3
    }
  ],
  "predictions": [
    {
      "ticker": "AAPL",
      "prediction": "BUY",
      "adjusted_confidence": 0.78,
      "signal_strength": "STRONG",
      "trend": "UPTREND"
    }
  ]
}
```

#### Console Summary

- Top 5 scoring stocks
- BUY/SELL signals with confidence
- Sector sentiment analysis
- Timing rule validations

### Advanced Configuration

```python
# Custom lookback period
ingester = HistoricalDataIngester(lookback_years=2)

# Custom scoring weights
app.scoring_system.weights = {
    'technical': 0.5,
    'sentiment': 0.2,
    'momentum': 0.2,
    'volatility': 0.1
}

# Different ML model
from sklearn.ensemble import GradientBoostingClassifier
app.prediction_engine.model = GradientBoostingClassifier(n_estimators=100)
```

### Performance

- **First Run**: ~3-7 minutes (downloads full 1-year history for 5 tickers)
- **Subsequent Runs**: ~1-2 minutes (incremental updates only)
- **Model Training**: ~10 seconds
- **Full Pipeline**: ~3-7 minutes first, ~1-2 minutes after

### Troubleshooting

**Timezone Error on Windows**
```bash
pip install tzdata
```

**No Market Data**
- Check internet connection
- Verify ticker symbols (e.g., 'AAPL' not 'Apple')
- Yahoo Finance may rate-limit; retry after delay

**Duplicate Data**
```python
# Clear cache to force fresh download
import shutil
shutil.rmtree('data_cache', ignore_errors=True)
```

---

## The Original Codebase: `claude/app/mp_v01/`

A point-in-time-correct research pipeline, built to make hindsight structurally impossible rather than merely discouraged.

| Module | What it guarantees |
|---|---|
| `pit/schema.py`, `pit/store.py` | Every record carries four timestamps. Only `available_time` is ever filterable. Revisions don't leak backwards. Syndicated copies collapse to one info event. |
| `labels/contract.py` | Label = binary sign of 5-trading-day forward log excess total return vs. SPY. Decision clock (15:45 ET) precedes the close it's scored against. Fails closed on unknown data. |
| `backtest/costs.py` | Spread/slippage/fee modeling; stale and wide quotes are rejected, not used. |
| `backtest/walkforward.py` | Chronological train/test splits with purge gap tied to label horizon, plus embargo. |
| `backtest/evaluate.py` | Noise floor via permutation test — distinguishes real edge from chance. Validated to read `NO_EDGE` on pure random data. |
| `gates/risk.py` | Deterministic `PASS` / `WATCH` / `PAPER_TRADE_CANDIDATE` decision gate, outside model judgment. Unknown/invalid inputs fail closed. |
| `adapters/yahoo_daily.py` | Free daily equity bars with realistic publication lag. |
| `adapters/eodhd_options.py` | Paid options chain adapter; token read from env only. |

### Original Quickstart

GUI (from repo root):
```bash
python gui.py               # run tests, fetch data, browse results
```

Command line:
```bash
cd claude/app/mp_v01
python run_all.py          # full zero-dependency test suite

pip install yfinance
python fetch_data.py --tickers SPY,QQQ,MSFT --chains
```

## Project Organization

- **Claude** — architecture, orchestration, adversarial code review, QC
- **Codex** — local execution, data ingestion, build
- **Specialist Personas** — domain analysis (sector intelligence, options research, bear-case evidence)

Deterministic risk gates sit outside every model's judgment. A model may only *propose*; `gates/risk.py` *decides*.

See `claude/scheduled_state/STATE.md` for current work list and decision log.

## Disclaimer

**This tool is for educational and research purposes only. It is not financial advice. Always conduct your own due diligence before making investment decisions. Past performance does not guarantee future results. Use at your own risk.**

---

**Last Updated**: August 13, 2026  
**Version**: 2.0.0 (with Market Intelligence Engine)
