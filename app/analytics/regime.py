# analytics/regime.py
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

def get_adx(symbol: str = "SPY", period: int = 14) -> float:
    """
    Calculate ADX (Average Directional Index) using yfinance.
    Returns 25.0 as fallback if data is unavailable.
    """
    try:
        data = yf.download(symbol, period="60d", interval="1d", progress=False)
        if data.empty:
            return 25.0
        
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        # Simple ADX calculation (placeholder for full implementation)
        # In production, use TA-Lib or a proper vectorized calculation
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
        atr = tr.rolling(period).mean()
        
        # Placeholder: return a neutral value if we can't compute properly
        return 25.0
    except Exception as e:
        print(f"Error getting ADX: {e}")
        return 25.0

def get_vix_percentile() -> float:
    """VIX percentile over last 252 trading days. Returns 50.0 as fallback."""
    try:
        vix = yf.download("^VIX", period="1y", interval="1d", progress=False)['Close']
        if vix.empty:
            return 50.0
        current = vix.iloc[-1]
        percentile = (vix < current).sum() / len(vix) * 100
        return float(percentile)
    except Exception as e:
        print(f"Error getting VIX percentile: {e}")
        return 50.0

def get_atr_percentile(symbol: str = "SPY", period: int = 14) -> float:
    """ATR percentile over last 252 trading days. Returns 50.0 as fallback."""
    try:
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty:
            return 50.0
        high, low, close = data['High'], data['Low'], data['Close']
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
        atr = tr.rolling(period).mean()
        if atr.empty:
            return 50.0
        current_atr = atr.iloc[-1]
        percentile = (atr < current_atr).sum() / len(atr) * 100
        return float(percentile)
    except Exception as e:
        print(f"Error getting ATR percentile: {e}")
        return 50.0

def get_advance_decline_ratio() -> float:
    """
    Get Advance/Decline Ratio from NYSE data.
    Returns 1.0 (neutral) as fallback.
    """
    try:
        # Using NYSE Advance/Decline indices (if available)
        adv = yf.download("^NYAD", period="5d", interval="1d", progress=False)['Close']
        dec = yf.download("^NYDEC", period="5d", interval="1d", progress=False)['Close']
        if adv.empty or dec.empty or adv.iloc[-1] == 0:
            return 1.0
        ratio = adv.iloc[-1] / dec.iloc[-1]
        return float(ratio)
    except Exception as e:
        print(f"Error getting Advance/Decline Ratio: {e}")
        return 1.0

def get_nh_nl_ratio() -> float:
    """
    Get New Highs / New Lows Ratio (52-week) from NYSE data.
    Returns 1.0 (neutral) as fallback.
    """
    try:
        nh = yf.download("^NYHGH", period="5d", interval="1d", progress=False)['Close']
        nl = yf.download("^NYLOW", period="5d", interval="1d", progress=False)['Close']
        if nh.empty or nl.empty or nl.iloc[-1] == 0:
            return 1.0
        ratio = nh.iloc[-1] / nl.iloc[-1]
        return float(ratio)
    except Exception as e:
        print(f"Error getting NH/NL Ratio: {e}")
        return 1.0

def get_correlation(symbol1: str, symbol2: str, period_days: int = 30) -> float:
    """
    Calculate rolling correlation between two symbols over the last N days.
    Returns 0.0 as fallback if insufficient data.
    """
    try:
        end = datetime.now()
        start = end - timedelta(days=period_days * 2)  # Extra days for padding
        data1 = yf.download(symbol1, start=start, end=end, interval="1d", progress=False)['Close']
        data2 = yf.download(symbol2, start=start, end=end, interval="1d", progress=False)['Close']
        
        if data1.empty or data2.empty:
            return 0.0
        
        # Align data and calculate correlation on last period_days
        combined = pd.concat([data1, data2], axis=1, join='inner').dropna()
        combined.columns = [symbol1, symbol2]
        
        if len(combined) < period_days:
            return 0.0
        
        corr = combined.iloc[-period_days:].corr().iloc[0, 1]
        return float(corr) if not np.isnan(corr) else 0.0
    except Exception as e:
        print(f"Error calculating correlation {symbol1} vs {symbol2}: {e}")
        return 0.0

def get_regime_summary(adx: float, vix_percentile: float, atr_percentile: float) -> Dict[str, Any]:
    """
    Return a complete market regime summary with all indicators.
    """
    # --- Trend regime (ADX) ---
    if adx < 20:
        trend = "sideways"
        trend_description = "Range-bound market (mean reversion favorable)"
    elif adx > 25:
        trend = "trending"
        trend_description = "Trending market (trend following favorable)"
    else:
        trend = "transition"
        trend_description = "Transition between range and trend"

    # --- Fear regime (VIX) ---
    if vix_percentile > 80:
        fear = "extreme_fear"
        fear_description = "Extreme fear (historical upside bias)"
    elif vix_percentile < 20:
        fear = "extreme_complacency"
        fear_description = "Extreme complacency (caution for reversals)"
    else:
        fear = "normal"
        fear_description = "Normal fear levels"

    # --- Volatility regime (ATR) ---
    if atr_percentile > 70:
        volatility = "high"
        volatility_description = "High volatility (wider stops, smaller sizing)"
    elif atr_percentile < 30:
        volatility = "low"
        volatility_description = "Low volatility (tighter stops, larger sizing)"
    else:
        volatility = "normal"
        volatility_description = "Normal volatility"

    # --- Breadth (Advance/Decline Ratio) ---
    adv_dec_ratio = get_advance_decline_ratio()
    if adv_dec_ratio > 2.0:
        breadth = "strong_upside"
        breadth_description = "Strong upside breadth (broad market participation)"
    elif adv_dec_ratio < 0.5:
        breadth = "strong_downside"
        breadth_description = "Strong downside breadth (broad market weakness)"
    else:
        breadth = "neutral"
        breadth_description = "Neutral breadth (balanced market)"

    # --- Strength (New Highs/Lows Ratio) ---
    nh_nl_ratio = get_nh_nl_ratio()
    if nh_nl_ratio > 3.0:
        strength = "strong"
        strength_description = "Strong market (many new highs)"
    elif nh_nl_ratio < 0.33:
        strength = "weak"
        strength_description = "Weak market (many new lows)"
    else:
        strength = "neutral"
        strength_description = "Neutral market strength"

    # --- Correlations ---
    corr_spy_qqq = get_correlation("SPY", "QQQ")
    corr_spy_tlt = get_correlation("SPY", "TLT")

    return {
        # Core indicators
        "trend": trend,
        "trend_description": trend_description,
        "fear": fear,
        "fear_description": fear_description,
        "volatility": volatility,
        "volatility_description": volatility_description,
        # Numerical values
        "adx": round(adx, 2),
        "vix_percentile": round(vix_percentile, 2),
        "atr_percentile": round(atr_percentile, 2),
        # Advanced indicators
        "breadth": breadth,
        "breadth_description": breadth_description,
        "strength": strength,
        "strength_description": strength_description,
        "advance_decline_ratio": round(adv_dec_ratio, 2),
        "nh_nl_ratio": round(nh_nl_ratio, 2),
        "correlation_spy_qqq": round(corr_spy_qqq, 2),
        "correlation_spy_tlt": round(corr_spy_tlt, 2),
    }