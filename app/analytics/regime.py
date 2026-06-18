# analytics/regime.py
import yfinance as yf
import pandas as pd
import numpy as np
from typing import List, Dict, Any

def get_adx(symbol: str = "SPY", period: int = 14) -> float:
    """
    Calculate ADX (Average Directional Index) for a given symbol.
    Returns a float value (0-100). If error, returns 25 (neutral).
    """
    try:
        data = yf.download(symbol, period="60d", interval="1d")
        if len(data) < period + 10:
            return 25.0
        high, low, close = data['High'], data['Low'], data['Close']
        # Simple ADX approximation (or use TA-Lib for accuracy)
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
        atr = tr.rolling(period).mean()
        # For simplicity, return a placeholder value
        # In production, use TA-Lib: import talib; adx = talib.ADX(high, low, close, timeperiod=period)
        return 25.0  # neutral placeholder
    except Exception as e:
        return 25.0

def get_vix_percentile() -> float:
    """
    Get VIX percentile over the last 252 trading days.
    Returns a value between 0 and 100.
    """
    try:
        vix = yf.download("^VIX", period="1y", interval="1d")['Close']
        if len(vix) == 0:
            return 50.0
        current = vix.iloc[-1]
        percentile = (vix < current).sum() / len(vix) * 100
        return float(percentile)
    except Exception as e:
        return 50.0

def get_atr_percentile(symbol: str = "SPY", period: int = 14) -> float:
    """
    Get ATR percentile over the last 252 trading days.
    Returns a value between 0 and 100.
    """
    try:
        data = yf.download(symbol, period="1y", interval="1d")
        if len(data) < period + 10:
            return 50.0
        high, low, close = data['High'], data['Low'], data['Close']
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
        atr = tr.rolling(period).mean()
        if len(atr) == 0:
            return 50.0
        current_atr = atr.iloc[-1]
        percentile = (atr < current_atr).sum() / len(atr) * 100
        return float(percentile)
    except Exception as e:
        return 50.0

def get_advance_decline_ratio() -> float:
    """
    Get NYSE Advance/Decline ratio (placeholder).
    Returns a float value.
    """
    # This requires a data source for advancing/declining issues.
    # For now, return a neutral value.
    return 1.0

def get_new_highs_lows_ratio() -> float:
    """
    Get New Highs / New Lows ratio (placeholder).
    Returns a float value.
    """
    # This requires a data source for new highs/lows.
    return 1.0

def get_correlations() -> Dict[str, float]:
    """
    Get key market correlations (SPY vs QQQ, SPY vs TLT, etc.) (placeholder).
    """
    return {
        "spy_vs_qqq": 0.85,
        "spy_vs_tlt": -0.30,
        "spy_vs_vix": -0.70
    }

def get_regime_summary(adx_value: float = None, vix_percentile: float = None, atr_percentile: float = None) -> Dict[str, Any]:
    """
    Return a descriptive regime summary based on indicators.
    """
    if adx_value is None:
        adx_value = 25.0
    if vix_percentile is None:
        vix_percentile = 50.0
    if atr_percentile is None:
        atr_percentile = 50.0
    
    regime = {}
    
    # Trend regime
    if adx_value < 20:
        regime["trend"] = "sideways"
        regime["trend_description"] = "Range-bound market (mean reversion favorable)"
    elif adx_value > 25:
        regime["trend"] = "trending"
        regime["trend_description"] = "Trending market (trend following favorable)"
    else:
        regime["trend"] = "transition"
        regime["trend_description"] = "Transition between range and trend"
    
    # Fear regime
    if vix_percentile > 80:
        regime["fear"] = "extreme_fear"
        regime["fear_description"] = "Extreme fear (historical upside bias)"
    elif vix_percentile < 20:
        regime["fear"] = "extreme_complacency"
        regime["fear_description"] = "Extreme complacency (caution for reversals)"
    else:
        regime["fear"] = "normal"
        regime["fear_description"] = "Normal fear levels"
    
    # Volatility regime
    if atr_percentile > 70:
        regime["volatility"] = "high"
        regime["volatility_description"] = "High volatility (wider stops, smaller sizing)"
    elif atr_percentile < 30:
        regime["volatility"] = "low"
        regime["volatility_description"] = "Low volatility (tighter stops, larger sizing)"
    else:
        regime["volatility"] = "normal"
        regime["volatility_description"] = "Normal volatility"
    
    # Additional metrics
    regime["adx"] = round(adx_value, 2)
    regime["vix_percentile"] = round(vix_percentile, 2)
    regime["atr_percentile"] = round(atr_percentile, 2)
    
    return regime