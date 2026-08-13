# Market Intelligence Engine

A comprehensive Python application for market data analysis, sector news aggregation, and predictive stock/option trading signals.

## Overview

The Market Intelligence Engine automates a complete investment workflow:

1. **Historical Data Ingestion** - Downloads 1-year of OHLCV data for any stock ticker
2. **Sector News Scraping** - Aggregates financial news and classifies by sector
3. **Unified Scoring** - Combines technical analysis, sentiment, and momentum into a single score (0-100)
4. **Predictive Modeling** - Uses Random Forest ML to predict 5-day price movements
5. **Timing Rules** - Applies precise entry/exit rules based on market conditions

## Features

### 🎯 Core Capabilities

- **Technical Indicators**: SMA, RSI, MACD, Bollinger Bands, Volume analysis
- **Sentiment Analysis**: Extracts market sentiment from news by sector
- **ML Predictions**: Trains Random Forest classifier on historical patterns
- **Timing Optimization**: Applies sophisticated timing rules to refine signals
- **Risk Management**: Volatility scoring and position sizing guidance

### 📊 Analysis Components

| Component | Purpose | Output |
|-----------|---------|--------|
| Historical Ingester | Downloads & enriches price data | OHLCV + Technical indicators |
| News Scraper | Collects sector news | Sentiment scores by sector |
| Scoring System | Aggregates all factors | Unified 0-100 score per ticker |
| Prediction Engine | ML-based forecasting | BUY/SELL/HOLD signals with confidence |
| Timing Rules | Entry/exit optimization | Trend, volume, RSI confirmation |

## Installation

### Prerequisites
- Python 3.9+
- pip (Python package manager)

### Setup

1. **Clone the repository**:
```bash
git clone https://github.com/tylerj-spec/MoneyPrinter.git
cd MoneyPrinter
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

**Note for Windows users**: If you encounter timezone errors, run:
```bash
pip install tzdata
```

3. **Verify installation**:
```python
python -c "import market_intelligence_engine; print('✓ Installation successful')"
```

## Quick Start

### Basic Usage

```python
from market_intelligence_engine import MarketIntelligenceApp

# Create app instance
app = MarketIntelligenceApp()

# Define stocks and sectors
TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'TSLA']
SECTOR_ETFS = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Finance': 'XLF'
}

# Run complete analysis
results = app.run_analysis(TICKERS, SECTOR_ETFS)

# Generate report
app.generate_report('analysis_report.json')

# Print summary
app.print_summary()
```

### Run the demo:
```bash
python -c "from market_intelligence_engine import main; main()"
```

## Detailed Usage

### 1. Historical Data Ingestion

```python
from market_intelligence_engine import HistoricalDataIngester

ingester = HistoricalDataIngester(lookback_years=1)

# Download 1 year of data for a ticker
aapl_data = ingester.ingest_stock_data('AAPL')

# Download sector ETF data
sector_etfs = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Energy': 'XLE'
}
sector_data = ingester.ingest_sector_data(sector_etfs)

# Export to CSV
ingester.export_to_csv('market_data')
```

**Output**: DataFrame with columns:
- OHLCV (Open, High, Low, Close, Volume)
- Technical indicators: SMA_20, SMA_50, SMA_200, RSI, MACD, Bollinger Bands
- Volume ratios, returns, volatility

### 2. Sector News Scraping

```python
from market_intelligence_engine import SectorNewsScraper

scraper = SectorNewsScraper()

# Scrape news
articles = scraper.scrape_news(max_articles=100)

# Get sentiment by sector
tech_sentiment = scraper.get_sector_sentiment('Technology')
print(f"Tech sentiment: {tech_sentiment:.2f}")  # 0-1 scale
```

### 3. Unified Scoring

```python
from market_intelligence_engine import UnifiedScoringSystem
import pandas as pd

scoring = UnifiedScoringSystem()

# Calculate scores for a ticker
market_data = ingester.get_market_data('AAPL')
sentiment = scraper.get_sector_sentiment('Technology')

score = scoring.generate_unified_score('AAPL', market_data, sentiment)
print(f"Overall score: {score['overall_score']}")
print(f"Technical: {score['technical_score']}")
print(f"Momentum: {score['momentum_score']}")
print(f"Volatility: {score['volatility_score']}")
```

**Scoring Weights**:
- Technical analysis: 40%
- Sentiment: 30%
- Momentum: 20%
- Volatility: 10%

### 4. Prediction & Timing Rules

```python
from market_intelligence_engine import PredictionEngine

engine = PredictionEngine()

# Train on multiple tickers
engine.train_model(TICKERS, ingester.market_data)

# Get prediction for a ticker
market_data = ingester.get_market_data('AAPL')
base_pred = engine.predict('AAPL', market_data)

# Apply timing rules
refined_pred = engine.apply_timing_rules(base_pred, market_data)

print(f"Signal: {refined_pred['prediction']}")
print(f"Confidence: {refined_pred['adjusted_confidence']:.3f}")
print(f"Trend: {refined_pred['trend']}")
print(f"RSI Signal: {refined_pred['rsi_signal']}")
```

**Prediction Output**:
- `prediction`: BUY / SELL / HOLD
- `confidence`: 0.0-1.0 (model confidence)
- `adjusted_confidence`: Confidence after timing rules applied
- `signal_strength`: STRONG / MODERATE / WEAK
- `trend`: UPTREND / DOWNTREND / NEUTRAL
- `volume_confirmation`: Boolean
- `rsi_signal`: OVERSOLD / OVERBOUGHT / NEUTRAL

## Timing Rules

The engine applies four sophisticated timing rules:

### Rule 1: Trend Confirmation
```
IF Close > SMA_50 > SMA_200 → UPTREND (+0.10 boost)
IF Close < SMA_50 < SMA_200 → DOWNTREND (-0.10 boost)
ELSE → NEUTRAL (0 boost)
```

### Rule 2: Volume Confirmation
```
IF Volume > 1.5x 20-day average → Confirmed (+0.05 boost)
```

### Rule 3: RSI Extremes
```
IF RSI < 30 → Oversold (+0.08 boost, potential reversal)
IF RSI > 70 → Overbought (-0.08 boost, potential pullback)
```

### Rule 4: Bollinger Band Position
```
IF Price < Lower Band → Mean reversion signal
IF Price > Upper Band → Potential pullback
```

## Output & Reporting

### Console Output Example
```
================================================================================
MARKET INTELLIGENCE ENGINE - SUMMARY REPORT
================================================================================

📊 TOP SCORING STOCKS
------------------------------------------------------------------------
1. NVDA: 72.45 (Technical: 75.20, Momentum: 68.90)
2. MSFT: 68.30 (Technical: 70.15, Momentum: 65.50)
3. AAPL: 65.10 (Technical: 68.40, Momentum: 62.30)

🎯 PREDICTIONS
------------------------------------------------------------------------
BUY Signals (3):
  • NVDA: STRONG - Confidence 0.782 (UPTREND)
  • MSFT: MODERATE - Confidence 0.668 (UPTREND)

SELL Signals (1):
  • TSLA: STRONG - Confidence 0.715 (DOWNTREND)

📰 SECTOR SENTIMENT
------------------------------------------------------------------------
  Technology: 0.72 🟢 Positive
  Healthcare: 0.55 🟡 Neutral
  Finance: 0.48 🟡 Neutral

================================================================================
```

### JSON Report Example
```json
{
  "timestamp": "2026-08-13T15:35:42.123456",
  "market_data_summary": {
    "AAPL": {
      "latest_close": 182.45,
      "period_high": 195.20,
      "period_low": 165.30,
      "records": 252
    }
  },
  "sector_sentiment": {
    "Technology": 0.72,
    "Healthcare": 0.55
  },
  "unified_scores": [
    {
      "ticker": "AAPL",
      "technical_score": 68.4,
      "momentum_score": 62.3,
      "volatility_score": 72.1,
      "sentiment_score": 72.0,
      "overall_score": 68.7,
      "timestamp": "2026-08-13T15:35:40.654321"
    }
  ],
  "predictions": [
    {
      "ticker": "AAPL",
      "prediction": "BUY",
      "confidence": 0.685,
      "signal_strength": "MODERATE",
      "probability_up": 0.685,
      "probability_down": 0.315,
      "trend": "UPTREND",
      "volume_confirmation": true,
      "rsi_signal": "NEUTRAL",
      "adjusted_confidence": 0.735
    }
  ]
}
```

## Configuration

### Customize Weights

```python
from market_intelligence_engine import UnifiedScoringSystem

scoring = UnifiedScoringSystem()

# Adjust weights
scoring.weights = {
    'technical': 0.5,   # More emphasis on technicals
    'sentiment': 0.2,   # Less emphasis on sentiment
    'momentum': 0.2,
    'volatility': 0.1
}
```

### Customize Tickers & Sectors

```python
# Add any tickers
TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA',  # Mega-cap tech
    'SPY', 'QQQ', 'IWM',  # Index ETFs
    'BTC-USD', 'ETH-USD',  # Crypto
]

# Map sectors to ETF representatives
SECTOR_ETFS = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Finance': 'XLF',
    'Energy': 'XLE',
    'Consumer': 'XLY',
    'Industrial': 'XLI',
    'Materials': 'XLB',
    'Real Estate': 'XLRE',
    'Utilities': 'XLU',
    'Telecom': 'XLC'
}
```

## Data Sources

### Market Data
- **Primary**: Yahoo Finance (yfinance)
- **Fallback**: Alternative: Alpha Vantage, IEX Cloud, Finnhub

### News Data
- **Synthetic for demo**: Replace with real APIs:
  - NewsAPI (newsapi.org)
  - Finnhub News
  - Alpha Vantage News
  - SEC Filings (edgar-online)

## Technical Architecture

```
┌─────────────────────────────────────────┐
│   MarketIntelligenceApp (Orchestrator)  │
└────────────┬────────────────────────────┘
             │
    ┌────────┼────────┬────────────┬─────────────┐
    │        │        │            │             │
    ▼        ▼        ▼            ▼             ▼
┌────────┐ ┌──────┐ ┌───────┐ ┌────────┐ ┌──────────┐
│History │ │ News │ │Scoring│ │ ML    │ │  Report │
│Ingester│ │Scrape│ │System │ │Engine │ │Generator│
└────────┘ └──────┘ └───────┘ └────────┘ └──────────┘
    │        │        │            │             │
    └────────┼────────┼────────────┼─────────────┘
             │
    ┌────────▼────────────────────┐
    │  Analysis Results (JSON)    │
    │  - Scores                   │
    │  - Predictions              │
    │  - Sentiment                │
    │  - Timing Rules Applied     │
    └─────────────────────────────┘
```

## Performance Considerations

### Data Ingestion
- ~5-10 seconds per ticker (1 year of daily data)
- Parallel downloads recommended for 20+ tickers
- Cached locally to avoid repeated downloads

### Model Training
- Uses Random Forest (50-100 trees) for speed
- Training time: 1-5 seconds for 5000+ samples
- Fits in memory for typical use cases

### Scoring
- <100ms per ticker after data is loaded
- Vectorized numpy operations for speed

## Limitations & Disclaimers

1. **Not Financial Advice**: This is for educational/research purposes only
2. **Synthetic Data**: Demo uses synthetic news; real APIs recommended
3. **Past Performance**: Historical data doesn't guarantee future results
4. **Market Gaps**: Gaps/halts during market hours not handled
5. **Slippage**: No slippage/execution costs modeled
6. **Weekend/Holiday**: Data gaps around holidays not filled

## Integration with MoneyPrinter Backtester

```python
from market_intelligence_engine import MarketIntelligenceApp
from labels.contract import build_label

# Run analysis
app = MarketIntelligenceApp()
results = app.run_analysis(TICKERS, SECTOR_ETFS)

# Extract predictions for backtesting
for pred in results['predictions']:
    if pred['prediction'] == 'BUY' and pred['adjusted_confidence'] > 0.7:
        # Create backtest label
        label = build_label(
            ticker=pred['ticker'],
            decision=pred['prediction'],
            confidence=pred['adjusted_confidence'],
            # ... other parameters
        )
```

## Troubleshooting

### Issue: ModuleNotFoundError: No module named 'tzdata'
**Solution**: 
```bash
pip install tzdata
```

### Issue: yfinance download hangs
**Solution**: Check internet connection, try different ticker

### Issue: No articles scraped
**Solution**: Replace with real news API (see Configuration section)

### Issue: Model not trained warning
**Solution**: Ensure data ingestion completed successfully for all tickers

## Future Enhancements

- [ ] Real API integrations (Finnhub, NewsAPI, IEX)
- [ ] Option-specific Greeks calculation
- [ ] Portfolio optimization (Markowitz)
- [ ] Advanced NLP sentiment analysis
- [ ] Reinforcement learning trader
- [ ] Real-time streaming data
- [ ] Risk correlation analysis
- [ ] Multi-timeframe analysis
- [ ] Earnings/event calendars
- [ ] Web dashboard interface

## Contributing

Contributions welcome! Areas needing work:
1. Real news API integration
2. Alternative technical indicators
3. Enhanced sentiment analysis (BERT/GPT-based)
4. Backtesting framework integration
5. Risk management improvements

## License

[Specify License - MIT, Apache 2.0, etc.]

## Contact & Support

Issues/Questions: Open a GitHub issue in the repository
Email: tylerjmcgovern@gmail.com

---

**⚠️ DISCLAIMER**: This tool is for educational purposes only. Do not use for actual trading without thorough backtesting and risk management. Past performance does not guarantee future results. Always consult with a financial advisor.
