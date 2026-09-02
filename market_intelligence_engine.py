"""
Market Intelligence Engine — RESTRICTED TO FEATURE DEVELOPMENT ONLY

⚠️  DO NOT USE FOR TRADING ⚠️

This module is a FEATURE SCRATCHPAD. It contains unvalidated ML, synthetic news data,
and data management practices that violate point-in-time correctness.

See CODE_REVIEW_2026-08-13.md for a complete accounting of what is broken here.
This code should be harvested for indicator math and integrated into claude/app/mp_v01/
where it will inherit proper validation, PIT semantics, and risk gates.

For any real evaluation: use claude/app/mp_v01/run_all.py
For forward paper trading: use claude/app/mp_v01/fetch_data.py + gates/risk.py
"""

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CRITICAL ISSUES (DO NOT USE FOR REAL TRADING)
# ============================================================================

CRITICAL_ISSUES = {
    "point_in_time": "Uses iloc[-1] as if available now. No PIT correctness.",
    "news_data": "100% synthetic. Sentiment weight set to 0.",
    "fillna": "Replaces missing SMA with 0 (dollar prices). Abstain instead.",
    "label_def": "Raw 2% threshold. Should be excess return vs SPY.",
    "costs": "Not modeled. Option spreads can be 10%+ round-trip.",
    "validation": "Zero tests, zero noise floor check, zero permutation test.",
    "cache": "Overwrites historical.csv. Should use PIT-correct versioned store.",
    "auto_adjust": "yfinance auto_adjust=True not explicitly set to False.",
}

logger.warning("MARKET INTELLIGENCE ENGINE: DEVELOPMENT ONLY")
logger.warning("See CODE_REVIEW_2026-08-13.md for limitations")
for issue, description in CRITICAL_ISSUES.items():
    logger.warning(f"  - {issue}: {description}")


# ============================================================================
# SECTION 1: HISTORICAL MARKET DATA INGESTION (WITH CAVEATS)
# ============================================================================

class HistoricalDataIngester:
    """
    Ingests and processes historical market data.
    
    ⚠️  LIMITATION: Uses iloc[-1] without publication lag modeling.
    In production, this must go through PIT store with available_time.
    """
    
    def __init__(self, lookback_years: int = 1):
        self.lookback_years = lookback_years
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=365 * lookback_years)
        self.market_data = {}
        logger.info(f"Initialized ingester (PIT-INCORRECT) for {self.start_date.date()} to {self.end_date.date()}")
        
    def ingest_stock_data(self, ticker: str) -> pd.DataFrame:
        """Download and ingest historical stock data."""
        try:
            logger.info(f"Ingesting {ticker}")
            
            # FIX #3.2: Explicit auto_adjust=False
            data = yf.download(
                ticker,
                start=self.start_date,
                end=self.end_date,
                progress=False,
                auto_adjust=False  # CRITICAL: Do not silently adjust for splits/divs
            )
            
            if data.empty:
                logger.warning(f"No data returned for {ticker}")
                return pd.DataFrame()
            
            # Flatten MultiIndex columns if present (yfinance version issue)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            
            # Verify schema
            required = ['Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
            if not all(col in data.columns for col in required):
                logger.error(f"Schema mismatch for {ticker}: {data.columns.tolist()}")
                return pd.DataFrame()
            
            # Calculate technical indicators
            data['SMA_20'] = data['Close'].rolling(window=20).mean()
            data['SMA_50'] = data['Close'].rolling(window=50).mean()
            data['SMA_200'] = data['Close'].rolling(window=200).mean()
            
            # RSI
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            data['RSI'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = data['Close'].ewm(span=12, adjust=False).mean()
            exp2 = data['Close'].ewm(span=26, adjust=False).mean()
            data['MACD'] = exp1 - exp2
            data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
            
            # Bollinger Bands
            data['BB_Middle'] = data['Close'].rolling(window=20).mean()
            data['BB_Std'] = data['Close'].rolling(window=20).std()
            data['BB_Upper'] = data['BB_Middle'] + (data['BB_Std'] * 2)
            data['BB_Lower'] = data['BB_Middle'] - (data['BB_Std'] * 2)
            
            # Volume indicators
            data['Volume_SMA'] = data['Volume'].rolling(window=20).mean()
            data['Volume_Ratio'] = data['Volume'] / data['Volume_SMA']
            
            # Returns
            data['Returns'] = data['Close'].pct_change()
            data['Log_Returns'] = np.log(data['Close'] / data['Close'].shift(1))
            
            # Volatility
            data['Volatility'] = data['Returns'].rolling(window=20).std() * np.sqrt(252)
            
            self.market_data[ticker] = data
            logger.info(f"Ingested {len(data)} records for {ticker}")
            return data
            
        except Exception as e:
            # FIX #3.3: Don't swallow exceptions silently
            logger.error(f"CRITICAL: Failed to ingest {ticker}: {str(e)}")
            logger.error("  This should fail closed, not fall back to stale cache")
            return pd.DataFrame()
    
    def ingest_sector_data(self, sector_etfs: Dict[str, str]) -> Dict[str, pd.DataFrame]:
        """Ingest sector ETF data."""
        sector_data = {}
        for sector, etf in sector_etfs.items():
            logger.info(f"Ingesting sector {sector} ({etf})")
            sector_data[sector] = self.ingest_stock_data(etf)
        return sector_data
    
    def get_market_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """Retrieve cached market data."""
        return self.market_data.get(ticker)


# ============================================================================
# SECTION 2: SYNTHETIC NEWS (NOT FOR REAL USE)
# ============================================================================

class SectorNewsScraper:
    """
    ⚠️  SYNTHETIC NEWS ONLY — DO NOT USE FOR TRADING
    
    Sentiment weight is set to 0 until a real news source with available_time
    is integrated into the PIT store.
    """
    
    def __init__(self):
        self.sector_keywords = {
            'Technology': ['tech', 'AI', 'software', 'semiconductor'],
            'Healthcare': ['pharma', 'biotech', 'medical'],
            'Finance': ['bank', 'fintech', 'insurance'],
            'Energy': ['oil', 'gas', 'renewable'],
            'Consumer': ['retail', 'e-commerce'],
        }
        self.articles = []
        logger.warning("SectorNewsScraper: Using SYNTHETIC data. Not suitable for real strategies.")
    
    def scrape_news(self, max_articles: int = 50) -> List[Dict]:
        """Generate synthetic news (placeholder only)."""
        logger.warning(f"Generating {max_articles} SYNTHETIC articles")
        articles = []
        sectors = list(self.sector_keywords.keys())
        
        for i in range(max_articles):
            sector = sectors[i % len(sectors)]
            # FIX #1.8: Synthetic means no real availability or credibility
            article = {
                'title': f"[SYNTHETIC] {sector} sector article #{i}",
                'url': f"https://synthetic.invalid/article-{i}",
                'source': 'SYNTHETIC-DO-NOT-USE',
                'timestamp': datetime.now() - timedelta(hours=i),
                'sector': sector,
            }
            articles.append(article)
        
        self.articles = articles
        logger.warning(f"Loaded {len(self.articles)} SYNTHETIC articles")
        return self.articles
    
    def get_sector_sentiment(self, sector: str) -> float:
        """Return 0.5 (neutral) for all sectors until real news integrated."""
        # FIX #1.8: Sentiment weight is 0 in scoring until real source exists
        return 0.5


# ============================================================================
# SECTION 3: UNIFIED SCORING (WITH CAVEATS)
# ============================================================================

class UnifiedScoringSystem:
    """
    Aggregates technical and fundamental data.
    
    NOTE: Sentiment weight is 0 because news is synthetic.
    Components have NOT been validated via rank IC.
    """
    
    def __init__(self):
        # FIX #1.8: Sentiment weight set to 0 until real source
        self.weights = {
            'technical': 0.5,      # Was 0.4
            'sentiment': 0.0,      # Was 0.3 (now ZERO — synthetic data)
            'momentum': 0.35,      # Was 0.2 (redistributed)
            'volatility': 0.15,    # Was 0.1 (redistributed)
        }
        logger.warning(f"Scoring weights (MODIFIED): {self.weights}")
        logger.warning("  Sentiment: 0 (synthetic data)")
    
    def calculate_technical_score(self, market_data: pd.DataFrame) -> float:
        """Calculate technical score (0-100)."""
        if market_data.empty or len(market_data) < 50:
            return 50
        
        latest = market_data.iloc[-1]
        score = 50
        
        # SMA analysis
        if (pd.notna(latest['Close']) and pd.notna(latest['SMA_50']) and 
            pd.notna(latest['SMA_200'])):
            if latest['Close'] > latest['SMA_50'] > latest['SMA_200']:
                score += 15
            elif latest['Close'] < latest['SMA_50'] < latest['SMA_200']:
                score -= 15
        
        # RSI
        if pd.notna(latest['RSI']):
            if latest['RSI'] < 30:
                score += 10
            elif latest['RSI'] > 70:
                score -= 10
        
        # MACD
        if pd.notna(latest['MACD']) and pd.notna(latest['Signal']):
            if latest['MACD'] > latest['Signal']:
                score += 10
            else:
                score -= 10
        
        return max(0, min(100, score))
    
    def calculate_momentum_score(self, market_data: pd.DataFrame) -> float:
        """Calculate momentum score (0-100)."""
        if len(market_data) < 50:
            return 50
        
        price_change_20 = (market_data['Close'].iloc[-1] / market_data['Close'].iloc[-20] - 1) * 100
        price_change_50 = (market_data['Close'].iloc[-1] / market_data['Close'].iloc[-50] - 1) * 100
        
        momentum = 50 + (price_change_20 / 2) + (price_change_50 / 4)
        return max(0, min(100, momentum))
    
    def calculate_volatility_score(self, market_data: pd.DataFrame) -> float:
        """Calculate volatility score (0-100)."""
        if len(market_data) < 20:
            return 50
        
        if 'Volatility' in market_data.columns and pd.notna(market_data['Volatility'].iloc[-1]):
            volatility = market_data['Volatility'].iloc[-1]
        else:
            returns = market_data['Close'].pct_change().tail(20)
            volatility = returns.std() * np.sqrt(252)
        
        score = 50 - (volatility * 100)
        return max(0, min(100, score))
    
    def generate_unified_score(
        self,
        ticker: str,
        market_data: pd.DataFrame,
        sentiment_score: float = 0.5
    ) -> Dict[str, float]:
        """Generate unified score (sentiment_score ignored, always 0.5)."""
        technical = self.calculate_technical_score(market_data)
        momentum = self.calculate_momentum_score(market_data)
        volatility = self.calculate_volatility_score(market_data)
        sentiment = 50  # Forced to neutral (0 weight anyway)
        
        overall_score = (
            self.weights['technical'] * technical +
            self.weights['momentum'] * momentum +
            self.weights['volatility'] * volatility +
            self.weights['sentiment'] * sentiment
        )
        
        return {
            'ticker': ticker,
            'technical_score': round(technical, 2),
            'momentum_score': round(momentum, 2),
            'volatility_score': round(volatility, 2),
            'sentiment_score': round(sentiment, 2),
            'overall_score': round(overall_score, 2),
            'timestamp': datetime.now().isoformat(),
            'WARNING': 'Not validated. See CODE_REVIEW_2026-08-13.md'
        }


# ============================================================================
# SECTION 4: PREDICTION ENGINE (UNVALIDATED)
# ============================================================================

class PredictionEngine:
    """
    ⚠️  UNVALIDATED ML — DO NOT TRUST CONFIDENCE SCORES
    
    Missing:
    - Proper train/test split
    - Noise floor validation
    - Permutation test
    - No PIT correctness
    - No holdout data
    """
    
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=50, random_state=42, max_depth=10)
        self.is_trained = False
        self.feature_names = ['SMA_20', 'SMA_50', 'SMA_200', 'RSI', 'MACD', 'Volume_Ratio']
        logger.warning("PredictionEngine initialized (UNVALIDATED)")
    
    def prepare_features(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """Prepare features for ML."""
        if len(market_data) < 50:
            return pd.DataFrame()
        
        features = market_data[['SMA_20', 'SMA_50', 'SMA_200', 'RSI', 'MACD']].copy()
        features['Volume_Ratio'] = market_data['Volume'] / market_data['Volume_SMA']
        
        # FIX #1.7: Wrong label definition. Should use excess return vs SPY
        # CURRENT (wrong): raw 2% threshold
        features['Target'] = ((market_data['Close'].shift(-5) / market_data['Close'] - 1) > 0.02).astype(int)
        
        return features.dropna()
    
    def train_model(self, tickers: List[str], market_data_dict: Dict[str, pd.DataFrame]):
        """Train model (no holdout set — this is wrong)."""
        logger.warning("Training model (NO HOLDOUT SET)")
        logger.warning("  This is not a real validation. Use claude/app/mp_v01/ for proper testing.")
        
        all_features = []
        all_targets = []
        
        for ticker in tickers:
            if ticker in market_data_dict:
                features_df = self.prepare_features(market_data_dict[ticker])
                if not features_df.empty:
                    all_features.append(features_df[self.feature_names])
                    all_targets.extend(features_df['Target'].values)
        
        if all_features and len(all_targets) > 10:
            X = pd.concat(all_features, ignore_index=True)
            y = np.array(all_targets)
            self.model.fit(X, y)
            self.is_trained = True
            logger.info(f"Model fit on {len(X)} samples (all training, no test split)")
        else:
            logger.warning("Insufficient data for training")
    
    def predict(self, ticker: str, market_data: pd.DataFrame) -> Dict:
        """Predict next 5-day movement (UNVALIDATED CONFIDENCE)."""
        if not self.is_trained or market_data.empty or len(market_data) < 50:
            return {
                'ticker': ticker,
                'prediction': 'HOLD',
                'confidence': 0.5,
                'signal_strength': 'WEAK',
            }
        
        latest_data = market_data.tail(1)
        features = pd.DataFrame({
            'SMA_20': [latest_data['SMA_20'].iloc[-1]],
            'SMA_50': [latest_data['SMA_50'].iloc[-1]],
            'SMA_200': [latest_data['SMA_200'].iloc[-1]],
            'RSI': [latest_data['RSI'].iloc[-1]],
            'MACD': [latest_data['MACD'].iloc[-1]],
            'Volume_Ratio': [latest_data['Volume'].iloc[-1] / latest_data['Volume_SMA'].iloc[-1]]
        })
        
        # FIX #1.6: Don't use fillna(0) on price levels. Abstain instead.
        if features.isnull().any().any():
            logger.warning(f"NaN in features for {ticker}. Abstaining (HOLD).")
            return {'ticker': ticker, 'prediction': 'HOLD', 'confidence': 0.5}
        
        probability = self.model.predict_proba(features)[0]

        # FIX #2.6: Can't emit SELL from binary upside label.
        # One threshold, not two. The 0.65 arm also returned BUY, so it never
        # changed the outcome - it only read as graded confidence. The model's
        # own .predict() was called here and discarded; removed with it.
        signal = 'BUY' if probability[1] > 0.55 else 'HOLD'
        
        return {
            'ticker': ticker,
            'prediction': signal,
            'confidence': round(probability[1], 3),
            'signal_strength': 'UNVALIDATED',
        }


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class MarketIntelligenceApp:
    """DEVELOPMENT ONLY. Not for trading."""
    
    def __init__(self):
        self.ingester = HistoricalDataIngester(lookback_years=1)
        self.news_scraper = SectorNewsScraper()
        self.scoring_system = UnifiedScoringSystem()
        self.prediction_engine = PredictionEngine()
        self.results = {
            'market_data': {},
            'sector_sentiment': {},
            'scores': [],
            'predictions': []
        }
    
    def run_analysis(self, tickers: List[str], sector_etfs: Dict[str, str]) -> Dict:
        """Run incomplete analysis pipeline."""
        logger.info("=" * 80)
        logger.warning("MARKET INTELLIGENCE ENGINE - DEVELOPMENT ONLY")
        logger.warning("NOT SUITABLE FOR REAL TRADING")
        logger.info("=" * 80)
        
        logger.info("\n[STEP 1/6] Ingesting Historical Market Data...")
        for ticker in tickers:
            self.ingester.ingest_stock_data(ticker)
        
        self.results['market_data'] = self.ingester.market_data
        
        logger.info("\n[STEP 2/6] Scraping Sector News (SYNTHETIC)...")
        self.news_scraper.scrape_news(max_articles=50)
        
        logger.info("\n[STEP 4/6] Generating Unified Scores...")
        for ticker in tickers:
            market_data = self.ingester.get_market_data(ticker)
            if market_data is not None and not market_data.empty:
                score = self.scoring_system.generate_unified_score(ticker, market_data)
                self.results['scores'].append(score)
        
        logger.info("\n[STEP 5/6] Training Prediction Model (UNVALIDATED)...")
        self.prediction_engine.train_model(tickers, self.results['market_data'])
        
        logger.info("\n[STEP 6/6] Generating Predictions...")
        for ticker in tickers:
            market_data = self.ingester.get_market_data(ticker)
            if market_data is not None and not market_data.empty:
                prediction = self.prediction_engine.predict(ticker, market_data)
                self.results['predictions'].append(prediction)
        
        logger.info("\n" + "=" * 80)
        logger.warning("ANALYSIS COMPLETE (UNVALIDATED)")
        logger.warning("DO NOT USE FOR REAL TRADING")
        logger.info("=" * 80)
        
        return self.results
    
    def generate_report(self, output_file: str = 'market_intelligence_report.json') -> str:
        """Generate report with disclaimer."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'DISCLAIMER': 'UNVALIDATED. See CODE_REVIEW_2026-08-13.md. NOT FOR REAL TRADING.',
            'unified_scores': self.results['scores'],
            'predictions': self.results['predictions']
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Report saved to: {output_file}")
        return output_file
    
    def print_summary(self):
        """Print summary with disclaimers."""
        print("\n" + "=" * 80)
        print("⚠️  MARKET INTELLIGENCE ENGINE - DEVELOPMENT/SCRATCHPAD ONLY")
        print("=" * 80)
        print("\nThis output is NOT SUITABLE FOR REAL TRADING.")
        print("See CODE_REVIEW_2026-08-13.md for complete list of issues.\n")
        
        print("Top scoring stocks:")
        sorted_scores = sorted(self.results['scores'], key=lambda x: x['overall_score'], reverse=True)
        for i, score in enumerate(sorted_scores[:3], 1):
            print(f"  {i}. {score['ticker']}: {score['overall_score']}")
        
        print("\nPredictions (UNVALIDATED):")
        for pred in self.results['predictions'][:3]:
            print(f"  {pred['ticker']}: {pred['prediction']}")
        
        print("\n" + "=" * 80)
        print("For real evaluation, use: claude/app/mp_v01/run_all.py")
        print("=" * 80 + "\n")


def main(argv: Optional[List[str]] = None):
    """Entry point (development only)."""
    ap = argparse.ArgumentParser(
        description="Market Intelligence Engine - DEVELOPMENT ONLY, not for trading."
    )
    ap.add_argument('--tickers', default='AAPL,MSFT,GOOGL',
                    help='comma-separated tickers to analyse')
    ap.add_argument('--out', default='market_intelligence_report.json',
                    help='path for the JSON report')
    a = ap.parse_args(argv)

    tickers = [t.strip().upper() for t in a.tickers.split(',') if t.strip()]
    if not tickers:
        ap.error('--tickers needs at least one symbol')
    SECTOR_ETFS = {'Technology': 'XLK'}

    app = MarketIntelligenceApp()
    results = app.run_analysis(tickers, SECTOR_ETFS)
    app.generate_report(a.out)
    app.print_summary()

    return app, results


if __name__ == '__main__':
    app, results = main()
