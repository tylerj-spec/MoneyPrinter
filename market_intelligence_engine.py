"""
Market Intelligence Engine
Integrates with MoneyPrinter's backtesting framework.

This module:
1. Ingests historical market data (1-year lookback)
2. Scrapes and aggregates sector news
3. Creates unified scoring system
4. Predicts stock/option picks with timing rules

Dependencies: yfinance, pandas, numpy, scikit-learn, requests, beautifulsoup4
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# SECTION 1: HISTORICAL MARKET DATA INGESTION
# ============================================================================

class HistoricalDataIngester:
    """Ingests and processes historical market data for the previous year."""
    
    def __init__(self, lookback_years: int = 1):
        self.lookback_years = lookback_years
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=365 * lookback_years)
        self.market_data = {}
        logger.info(f"Initialized ingester for period: {self.start_date.date()} to {self.end_date.date()}")
        
    def ingest_stock_data(self, ticker: str) -> pd.DataFrame:
        """
        Download and ingest historical stock data.
        
        Args:
            ticker: Stock symbol (e.g., 'AAPL')
            
        Returns:
            DataFrame with OHLCV data and technical indicators
        """
        try:
            logger.info(f"Ingesting historical data for {ticker}")
            data = yf.download(
                ticker,
                start=self.start_date,
                end=self.end_date,
                progress=False
            )
            
            if data.empty:
                logger.warning(f"No data returned for {ticker}")
                return pd.DataFrame()
            
            # Calculate technical indicators
            data['SMA_20'] = data['Close'].rolling(window=20).mean()
            data['SMA_50'] = data['Close'].rolling(window=50).mean()
            data['SMA_200'] = data['Close'].rolling(window=200).mean()
            
            # RSI (Relative Strength Index)
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
            
            # Daily returns
            data['Returns'] = data['Close'].pct_change()
            data['Log_Returns'] = np.log(data['Close'] / data['Close'].shift(1))
            
            # Volatility (20-day rolling)
            data['Volatility'] = data['Returns'].rolling(window=20).std() * np.sqrt(252)
            
            self.market_data[ticker] = data
            logger.info(f"Successfully ingested {len(data)} records for {ticker}")
            return data
            
        except Exception as e:
            logger.error(f"Error ingesting data for {ticker}: {str(e)}")
            return pd.DataFrame()
    
    def ingest_sector_data(self, sector_etfs: Dict[str, str]) -> Dict[str, pd.DataFrame]:
        """
        Ingest historical data for sector ETFs.
        
        Args:
            sector_etfs: Dict mapping sector names to ETF tickers
            
        Returns:
            Dict with sector data
        """
        sector_data = {}
        for sector, etf in sector_etfs.items():
            logger.info(f"Ingesting sector data for {sector} ({etf})")
            sector_data[sector] = self.ingest_stock_data(etf)
        return sector_data
    
    def get_market_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """Retrieve cached market data."""
        return self.market_data.get(ticker)
    
    def export_to_csv(self, output_dir: str = 'market_data'):
        """Export all market data to CSV files."""
        os.makedirs(output_dir, exist_ok=True)
        for ticker, data in self.market_data.items():
            path = os.path.join(output_dir, f'{ticker}_historical.csv')
            data.to_csv(path)
            logger.info(f"Exported {ticker} to {path}")


# ============================================================================
# SECTION 2: SECTOR NEWS SCRAPING & AGGREGATION
# ============================================================================

class SectorNewsScraper:
    """Scrapes and processes sector news from financial news sources."""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.sector_keywords = {
            'Technology': ['tech', 'AI', 'software', 'semiconductor', 'cloud', 'cybersecurity'],
            'Healthcare': ['pharma', 'biotech', 'medical', 'healthcare', 'drug', 'FDA'],
            'Finance': ['bank', 'fintech', 'insurance', 'financial', 'investment', 'crypto'],
            'Energy': ['oil', 'gas', 'renewable', 'energy', 'coal', 'solar'],
            'Consumer': ['retail', 'consumer', 'e-commerce', 'consumer goods', 'brand'],
            'Industrial': ['manufacturing', 'industrial', 'infrastructure', 'aerospace'],
            'Materials': ['mining', 'materials', 'chemical', 'steel', 'commodity'],
            'Real Estate': ['real estate', 'property', 'REIT', 'housing'],
            'Utilities': ['utility', 'electric', 'water', 'power'],
            'Telecom': ['telecom', 'communication', 'wireless', '5G']
        }
        self.articles = []
        logger.info("Initialized SectorNewsScraper")
    
    def scrape_news(self, max_articles: int = 50) -> List[Dict]:
        """
        Scrape recent news articles from financial sources.
        
        Args:
            max_articles: Maximum number of articles to scrape
            
        Returns:
            List of article dictionaries
        """
        logger.info(f"Scraping news articles (target: {max_articles})")
        articles = []
        
        # In production, use dedicated APIs like:
        # - NewsAPI (newsapi.org)
        # - Finnhub (finnhub.io)
        # - IEX Cloud (iexcloud.io)
        # - Alpha Vantage (alphavantage.co)
        
        # For demo purposes, create synthetic news
        synthetic_articles = self._generate_synthetic_news(max_articles)
        articles.extend(synthetic_articles)
        
        self.articles = articles
        logger.info(f"Collected {len(self.articles)} articles")
        return self.articles
    
    def _generate_synthetic_news(self, count: int) -> List[Dict]:
        """Generate synthetic news for demo purposes."""
        sectors = list(self.sector_keywords.keys())
        sentiments = ['positive', 'negative', 'neutral']
        
        articles = []
        for i in range(count):
            sector = sectors[i % len(sectors)]
            sentiment = sentiments[i % len(sentiments)]
            
            article = {
                'title': f"{sector} sector shows {sentiment} momentum",
                'url': f"https://news.example.com/article-{i}",
                'source': 'synthetic-demo',
                'timestamp': datetime.now() - timedelta(hours=i),
                'sector': sector,
                'sentiment_keyword': sentiment
            }
            articles.append(article)
        
        return articles
    
    def _classify_sector(self, text: str) -> str:
        """Classify article to sector based on keywords."""
        text_lower = text.lower()
        
        for sector, keywords in self.sector_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return sector
        
        return 'General'
    
    def get_sector_sentiment(self, sector: str) -> float:
        """
        Calculate sentiment score for a sector (0-1).
        
        Args:
            sector: Sector name
            
        Returns:
            Sentiment score (0=very negative, 1=very positive)
        """
        sector_articles = [a for a in self.articles if a['sector'] == sector]
        
        if not sector_articles:
            return 0.5  # Neutral
        
        # Calculate sentiment
        sentiment_score = 0
        for article in sector_articles:
            if 'sentiment_keyword' in article:
                if article['sentiment_keyword'] == 'positive':
                    sentiment_score += 1
                elif article['sentiment_keyword'] == 'negative':
                    sentiment_score -= 1
        
        # Normalize to 0-1 range
        normalized = 0.5 + (sentiment_score / (len(sector_articles) * 2))
        return max(0, min(1, normalized))


# ============================================================================
# SECTION 3: UNIFIED SCORING SYSTEM
# ============================================================================

class UnifiedScoringSystem:
    """Aggregates technical, sentiment, and fundamental data into unified scores."""
    
    def __init__(self):
        self.weights = {
            'technical': 0.4,
            'sentiment': 0.3,
            'momentum': 0.2,
            'volatility': 0.1
        }
        logger.info(f"Scoring weights: {self.weights}")
    
    def calculate_technical_score(self, market_data: pd.DataFrame) -> float:
        """
        Calculate technical score based on indicators (0-100).
        
        Args:
            market_data: DataFrame with OHLCV and technical indicators
            
        Returns:
            Technical score (0-100)
        """
        if market_data.empty or len(market_data) < 50:
            return 50  # Neutral
        
        latest = market_data.iloc[-1]
        score = 50  # Base score
        
        # SMA analysis
        if latest['Close'] > latest['SMA_50'] > latest['SMA_200']:
            score += 15  # Bullish trend
        elif latest['Close'] < latest['SMA_50'] < latest['SMA_200']:
            score -= 15  # Bearish trend
        
        # RSI analysis
        if pd.notna(latest['RSI']):
            if latest['RSI'] < 30:
                score += 10  # Oversold
            elif latest['RSI'] > 70:
                score -= 10  # Overbought
        
        # MACD analysis
        if pd.notna(latest['MACD']) and pd.notna(latest['Signal']):
            if latest['MACD'] > latest['Signal']:
                score += 10  # Bullish
            else:
                score -= 10  # Bearish
        
        # Bollinger Bands
        if pd.notna(latest['BB_Upper']) and pd.notna(latest['BB_Lower']):
            if latest['Close'] < latest['BB_Lower']:
                score += 8  # Below lower band
            elif latest['Close'] > latest['BB_Upper']:
                score -= 8  # Above upper band
        
        return max(0, min(100, score))
    
    def calculate_momentum_score(self, market_data: pd.DataFrame) -> float:
        """
        Calculate momentum score based on price changes (0-100).
        
        Args:
            market_data: DataFrame with price data
            
        Returns:
            Momentum score (0-100)
        """
        if len(market_data) < 50:
            return 50
        
        # 20-day price change
        price_change_20 = (market_data['Close'].iloc[-1] / market_data['Close'].iloc[-20] - 1) * 100
        
        # 50-day price change
        price_change_50 = (market_data['Close'].iloc[-1] / market_data['Close'].iloc[-50] - 1) * 100
        
        momentum = 50 + (price_change_20 / 2) + (price_change_50 / 4)
        return max(0, min(100, momentum))
    
    def calculate_volatility_score(self, market_data: pd.DataFrame) -> float:
        """
        Calculate volatility score (lower volatility = higher score).
        
        Args:
            market_data: DataFrame with price data
            
        Returns:
            Volatility score (0-100, where 100 = low volatility)
        """
        if len(market_data) < 20:
            return 50
        
        # Use the Volatility column if available, otherwise calculate
        if 'Volatility' in market_data.columns and pd.notna(market_data['Volatility'].iloc[-1]):
            volatility = market_data['Volatility'].iloc[-1]
        else:
            returns = market_data['Close'].pct_change().tail(20)
            volatility = returns.std() * np.sqrt(252)
        
        # Inverse relationship: higher volatility = lower score
        score = 50 - (volatility * 100)
        return max(0, min(100, score))
    
    def generate_unified_score(
        self,
        ticker: str,
        market_data: pd.DataFrame,
        sentiment_score: float
    ) -> Dict[str, float]:
        """
        Generate unified score combining all factors.
        
        Args:
            ticker: Stock symbol
            market_data: Historical price data
            sentiment_score: Sentiment score (0-1)
            
        Returns:
            Dictionary with component scores and overall score
        """
        technical = self.calculate_technical_score(market_data)
        momentum = self.calculate_momentum_score(market_data)
        volatility = self.calculate_volatility_score(market_data)
        
        # Convert sentiment to 0-100 scale
        sentiment = sentiment_score * 100
        
        # Calculate weighted score
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
            'timestamp': datetime.now().isoformat()
        }


# ============================================================================
# SECTION 4: PREDICTION ENGINE WITH TIMING RULES
# ============================================================================

class PredictionEngine:
    """Predicts stock/option picks using ML and timing rules."""
    
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=50, random_state=42, max_depth=10)
        self.is_trained = False
        self.feature_names = [
            'SMA_20', 'SMA_50', 'SMA_200', 'RSI', 'MACD', 'Volume_Ratio'
        ]
        logger.info("Initialized PredictionEngine")
    
    def prepare_features(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare features for ML model.
        
        Args:
            market_data: Historical market data
            
        Returns:
            DataFrame with features
        """
        if len(market_data) < 50:
            return pd.DataFrame()
        
        features = market_data[['SMA_20', 'SMA_50', 'SMA_200', 'RSI', 'MACD']].copy()
        
        # Add volume ratio
        features['Volume_Ratio'] = market_data['Volume'] / market_data['Volume_SMA']
        
        # Forward-looking label: 1 if price goes up >2% in next 5 days, 0 otherwise
        features['Target'] = (
            (market_data['Close'].shift(-5) / market_data['Close'] - 1) > 0.02
        ).astype(int)
        
        # Drop NaN values
        features = features.dropna()
        
        return features
    
    def train_model(self, tickers: List[str], market_data_dict: Dict[str, pd.DataFrame]):
        """
        Train prediction model on historical data.
        
        Args:
            tickers: List of ticker symbols
            market_data_dict: Dictionary of market data by ticker
        """
        logger.info("Training prediction model...")
        
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
            logger.info(f"Model trained on {len(X)} samples")
        else:
            logger.warning("Insufficient data for model training")
    
    def predict(self, ticker: str, market_data: pd.DataFrame) -> Dict:
        """
        Predict next 5-day price movement.
        
        Args:
            ticker: Stock symbol
            market_data: Market data
            
        Returns:
            Prediction dictionary
        """
        if not self.is_trained or market_data.empty or len(market_data) < 50:
            return {
                'ticker': ticker,
                'prediction': 'HOLD',
                'confidence': 0.5,
                'signal_strength': 'WEAK',
                'probability_up': 0.5,
                'probability_down': 0.5
            }
        
        # Prepare features for latest data
        latest_data = market_data.tail(1)
        features = pd.DataFrame({
            'SMA_20': [latest_data['SMA_20'].iloc[-1]],
            'SMA_50': [latest_data['SMA_50'].iloc[-1]],
            'SMA_200': [latest_data['SMA_200'].iloc[-1]],
            'RSI': [latest_data['RSI'].iloc[-1]],
            'MACD': [latest_data['MACD'].iloc[-1]],
            'Volume_Ratio': [latest_data['Volume'].iloc[-1] / latest_data['Volume_SMA'].iloc[-1]]
        })
        
        # Handle NaN values
        features = features.fillna(0)
        
        # Get prediction and probability
        prediction = self.model.predict(features)[0]
        probability = self.model.predict_proba(features)[0]
        
        # Determine signal
        if probability[1] > 0.65:
            signal = 'BUY'
            confidence = probability[1]
            strength = 'STRONG'
        elif probability[1] > 0.55:
            signal = 'BUY'
            confidence = probability[1]
            strength = 'MODERATE'
        elif probability[0] > 0.65:
            signal = 'SELL'
            confidence = probability[0]
            strength = 'STRONG'
        else:
            signal = 'HOLD'
            confidence = max(probability)
            strength = 'WEAK'
        
        return {
            'ticker': ticker,
            'prediction': signal,
            'confidence': round(confidence, 3),
            'signal_strength': strength,
            'probability_up': round(probability[1], 3),
            'probability_down': round(probability[0], 3)
        }
    
    def apply_timing_rules(self, prediction: Dict, market_data: pd.DataFrame) -> Dict:
        """
        Apply timing rules to refine predictions.
        
        Args:
            prediction: Base prediction
            market_data: Market data for timing analysis
            
        Returns:
            Refined prediction with timing
        """
        if market_data.empty or len(market_data) < 50:
            return prediction
        
        latest = market_data.iloc[-1]
        refined = prediction.copy()
        timing_boost = 0
        
        # Timing Rule 1: Check if we're in a strong uptrend
        if (pd.notna(latest['Close']) and pd.notna(latest['SMA_50']) and 
            pd.notna(latest['SMA_200']) and latest['Close'] > latest['SMA_50'] > latest['SMA_200']):
            refined['trend'] = 'UPTREND'
            timing_boost += 0.1
        # Timing Rule 2: Check if we're in a strong downtrend
        elif (pd.notna(latest['Close']) and pd.notna(latest['SMA_50']) and 
              pd.notna(latest['SMA_200']) and latest['Close'] < latest['SMA_50'] < latest['SMA_200']):
            refined['trend'] = 'DOWNTREND'
            timing_boost -= 0.1
        else:
            refined['trend'] = 'NEUTRAL'
        
        # Timing Rule 3: Volume confirmation
        if (pd.notna(latest['Volume']) and pd.notna(latest['Volume_SMA']) and 
            latest['Volume'] > latest['Volume_SMA'] * 1.5):
            refined['volume_confirmation'] = True
            timing_boost += 0.05
        else:
            refined['volume_confirmation'] = False
        
        # Timing Rule 4: RSI extremes
        if pd.notna(latest['RSI']):
            if latest['RSI'] < 30:
                refined['rsi_signal'] = 'OVERSOLD'
                timing_boost += 0.08
            elif latest['RSI'] > 70:
                refined['rsi_signal'] = 'OVERBOUGHT'
                timing_boost -= 0.08
            else:
                refined['rsi_signal'] = 'NEUTRAL'
        
        refined['timing_boost'] = round(timing_boost, 3)
        refined['adjusted_confidence'] = round(max(0, min(1, prediction['confidence'] + timing_boost)), 3)
        
        return refined


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class MarketIntelligenceApp:
    """Main application orchestrating all components."""
    
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
        """
        Run complete market analysis pipeline.
        
        Args:
            tickers: List of stock tickers to analyze
            sector_etfs: Dict of sector names to ETF tickers
            
        Returns:
            Analysis results
        """
        logger.info("=" * 80)
        logger.info("MARKET INTELLIGENCE ENGINE - ANALYSIS START")
        logger.info("=" * 80)
        
        # Step 1: Ingest historical market data
        logger.info("\n[STEP 1/6] Ingesting Historical Market Data...")
        for ticker in tickers:
            self.ingester.ingest_stock_data(ticker)
        
        sector_data = self.ingester.ingest_sector_data(sector_etfs)
        self.results['market_data'] = self.ingester.market_data
        
        # Step 2: Scrape sector news
        logger.info("\n[STEP 2/6] Scraping Sector News...")
        self.news_scraper.scrape_news(max_articles=50)
        
        # Step 3: Calculate sector sentiment
        logger.info("\n[STEP 3/6] Calculating Sector Sentiment...")
        for sector in sector_etfs.keys():
            sentiment = self.news_scraper.get_sector_sentiment(sector)
            self.results['sector_sentiment'][sector] = sentiment
            logger.info(f"  {sector}: {sentiment:.2f}")
        
        # Step 4: Generate unified scores
        logger.info("\n[STEP 4/6] Generating Unified Scores...")
        for ticker in tickers:
            market_data = self.ingester.get_market_data(ticker)
            if market_data is not None and not market_data.empty:
                sentiment = self.results['sector_sentiment'].get('Technology', 0.5)
                score = self.scoring_system.generate_unified_score(ticker, market_data, sentiment)
                self.results['scores'].append(score)
                logger.info(f"  {ticker}: {score['overall_score']}")
        
        # Step 5: Train prediction model
        logger.info("\n[STEP 5/6] Training Prediction Model...")
        self.prediction_engine.train_model(tickers, self.results['market_data'])
        
        # Step 6: Generate predictions
        logger.info("\n[STEP 6/6] Generating Predictions with Timing Rules...")
        for ticker in tickers:
            market_data = self.ingester.get_market_data(ticker)
            if market_data is not None and not market_data.empty:
                base_prediction = self.prediction_engine.predict(ticker, market_data)
                prediction = self.prediction_engine.apply_timing_rules(base_prediction, market_data)
                self.results['predictions'].append(prediction)
                logger.info(f"  {ticker}: {prediction['prediction']}")
        
        logger.info("\n" + "=" * 80)
        logger.info("ANALYSIS COMPLETE")
        logger.info("=" * 80)
        
        return self.results
    
    def generate_report(self, output_file: str = 'market_intelligence_report.json') -> str:
        """Generate comprehensive analysis report."""
        logger.info(f"\nGenerating report: {output_file}")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'market_data_summary': {
                ticker: {
                    'latest_close': float(data['Close'].iloc[-1]),
                    'period_high': float(data['Close'].max()),
                    'period_low': float(data['Close'].min()),
                    'records': len(data)
                }
                for ticker, data in self.results['market_data'].items()
            },
            'sector_sentiment': self.results['sector_sentiment'],
            'unified_scores': self.results['scores'],
            'predictions': self.results['predictions']
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Report saved to: {output_file}")
        return output_file
    
    def print_summary(self):
        """Print analysis summary to console."""
        print("\n" + "=" * 80)
        print("MARKET INTELLIGENCE ENGINE - SUMMARY REPORT")
        print("=" * 80)
        
        print("\n📊 TOP SCORING STOCKS")
        print("-" * 80)
        sorted_scores = sorted(self.results['scores'], key=lambda x: x['overall_score'], reverse=True)
        for i, score in enumerate(sorted_scores[:5], 1):
            print(f"{i}. {score['ticker']}: {score['overall_score']} "
                  f"(Technical: {score['technical_score']}, Momentum: {score['momentum_score']})")
        
        print("\n🎯 PREDICTIONS")
        print("-" * 80)
        buy_signals = [p for p in self.results['predictions'] if p['prediction'] == 'BUY']
        sell_signals = [p for p in self.results['predictions'] if p['prediction'] == 'SELL']
        
        if buy_signals:
            print(f"BUY Signals ({len(buy_signals)}):")
            for pred in buy_signals:
                print(f"  • {pred['ticker']}: {pred['signal_strength']} - "
                      f"Confidence {pred['adjusted_confidence']:.3f}")
        
        if sell_signals:
            print(f"\nSELL Signals ({len(sell_signals)}):")
            for pred in sell_signals:
                print(f"  • {pred['ticker']}: {pred['signal_strength']} - "
                      f"Confidence {pred['adjusted_confidence']:.3f}")
        
        if not buy_signals and not sell_signals:
            print("No strong signals generated")
        
        print("\n📰 SECTOR SENTIMENT")
        print("-" * 80)
        for sector, sentiment in self.results['sector_sentiment'].items():
            if sentiment > 0.6:
                label = "🟢 Positive"
            elif sentiment < 0.4:
                label = "🔴 Negative"
            else:
                label = "🟡 Neutral"
            print(f"  {sector}: {sentiment:.2f} {label}")
        
        print("\n" + "=" * 80)


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Main entry point for the application."""
    
    # Configuration
    TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'TSLA']
    
    SECTOR_ETFS = {
        'Technology': 'XLK',
        'Healthcare': 'XLV',
        'Finance': 'XLF'
    }
    
    # Initialize and run application
    app = MarketIntelligenceApp()
    results = app.run_analysis(TICKERS, SECTOR_ETFS)
    
    # Generate report and summary
    app.generate_report('market_intelligence_report.json')
    app.print_summary()
    
    return app, results


if __name__ == '__main__':
    app, results = main()
