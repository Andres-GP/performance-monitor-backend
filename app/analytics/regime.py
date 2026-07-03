# analytics/regime.py
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mapeo de futuros a tickers de Yahoo Finance (con =F)
FUTURE_TO_YF = {
    "ES": "ES=F",
    "GC": "GC=F",
    "NQ": "NQ=F",
    "CL": "CL=F",
    "NG": "NG=F",
    "ZB": "ZB=F",
    "ZN": "ZN=F",
    "ZF": "ZF=F",
    "ZT": "ZT=F",
}

# Mapeo de futuros a ETFs equivalentes (fallback)
FUTURE_TO_ETF = {
    "ES": "SPY",
    "GC": "GLD",
    "NQ": "QQQ",
    "CL": "USO",
    "NG": "UNG",
    "ZB": "TLT",
    "ZN": "TLT",
    "ZF": "TLT",
    "ZT": "TLT",
}

def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calcula el ADX de forma vectorizada usando pandas/numpy.
    Devuelve una Serie con el ADX para cada fecha.
    """
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    up_move = high - high.shift()
    down_move = low.shift() - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    plus_dm_series = pd.Series(plus_dm, index=high.index)
    minus_dm_series = pd.Series(minus_dm, index=high.index)

    plus_di = 100 * (plus_dm_series.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm_series.rolling(period).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    return adx

def get_adx(symbol: str = "SPY", period: int = 14) -> float:
    """
    Calculate ADX (Average Directional Index) using yfinance.
    Returns 25.0 as fallback if data is unavailable.
    """
    try:
        data = yf.download(symbol, period="60d", interval="1d", progress=False)
        if data.empty or len(data) < period + 10:
            logger.warning(f"ADX: Insufficient data for {symbol}")
            return 25.0

        adx = calculate_adx(data['High'], data['Low'], data['Close'], period)
        if adx.dropna().empty:
            return 25.0

        return float(adx.iloc[-1])
    except Exception as e:
        logger.error(f"Error calculating ADX for {symbol}: {e}")
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
        logger.error(f"Error getting VIX percentile: {e}")
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
        logger.error(f"Error getting ATR percentile: {e}")
        return 50.0

def get_advance_decline_ratio() -> float:
    """
    Get Advance/Decline Ratio from NYSE data.
    Returns 1.0 (neutral) as fallback.
    """
    try:
        adv = yf.download("^NYAD", period="5d", interval="1d", progress=False)['Close']
        dec = yf.download("^NYDEC", period="5d", interval="1d", progress=False)['Close']
        if adv.empty or dec.empty or adv.iloc[-1] == 0:
            return 1.0
        ratio = adv.iloc[-1] / dec.iloc[-1]
        return float(ratio)
    except Exception as e:
        logger.error(f"Error getting Advance/Decline Ratio: {e}")
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
        logger.error(f"Error getting NH/NL Ratio: {e}")
        return 1.0

def get_correlation(symbol1: str, symbol2: str, period_days: int = 30) -> float:
    """
    Calculate rolling correlation between two symbols over the last N days.
    Returns 0.0 as fallback if insufficient data.
    """
    try:
        end = datetime.now()
        start = end - timedelta(days=period_days * 2)
        data1 = yf.download(symbol1, start=start, end=end, interval="1d", progress=False)['Close']
        data2 = yf.download(symbol2, start=start, end=end, interval="1d", progress=False)['Close']
        
        if data1.empty or data2.empty:
            return 0.0
        
        combined = pd.concat([data1, data2], axis=1, join='inner').dropna()
        combined.columns = [symbol1, symbol2]
        
        if len(combined) < period_days:
            return 0.0
        
        corr = combined.iloc[-period_days:].corr().iloc[0, 1]
        return float(corr) if not np.isnan(corr) else 0.0
    except Exception as e:
        logger.error(f"Error calculating correlation {symbol1} vs {symbol2}: {e}")
        return 0.0

def get_average_daily_volume(symbol: str) -> float:
    """
    Obtiene el volumen promedio diario de los últimos 20 días.
    Si el símbolo es un futuro, usa el ticker con '=F'.
    Si falla, intenta con el ETF equivalente.
    Si todo falla, devuelve 0.0.
    """
    # Limpiar símbolo (quitar espacios, etc.)
    symbol = symbol.strip().upper()
    
    # Lista de tickers a intentar (orden de prioridad)
    tickers_to_try = []
    
    # 1. Si es un futuro conocido, usar el ticker con =F
    if symbol in FUTURE_TO_YF:
        tickers_to_try.append(FUTURE_TO_YF[symbol])
    else:
        tickers_to_try.append(symbol)
    
    # 2. Si es un futuro y tiene ETF equivalente, añadirlo como fallback
    if symbol in FUTURE_TO_ETF:
        tickers_to_try.append(FUTURE_TO_ETF[symbol])
    
    # 3. Si el símbolo original no es futuro, pero podría ser un ETF directamente,
    #    ya lo tenemos en la lista.
    
    for ticker in tickers_to_try:
        try:
            data = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not data.empty:
                avg_volume = data['Volume'].mean()
                if not np.isnan(avg_volume) and avg_volume > 0:
                    logger.debug(f"Volume for {symbol} using {ticker}: {avg_volume}")
                    return float(avg_volume)
        except Exception as e:
            logger.warning(f"Failed to get volume for {ticker}: {e}")
            continue
    
    logger.warning(f"No volume data found for {symbol} (tried {tickers_to_try})")
    return 0.0

def get_regime_summary(adx: float, vix_percentile: float, atr_percentile: float) -> Dict[str, Any]:
    """
    Return a complete market regime summary with all indicators.
    """
    if adx < 20:
        trend = "sideways"
        trend_description = "Range-bound market (mean reversion favorable)"
    elif adx > 25:
        trend = "trending"
        trend_description = "Trending market (trend following favorable)"
    else:
        trend = "transition"
        trend_description = "Transition between range and trend"

    if vix_percentile > 80:
        fear = "extreme_fear"
        fear_description = "Extreme fear (historical upside bias)"
    elif vix_percentile < 20:
        fear = "extreme_complacency"
        fear_description = "Extreme complacency (caution for reversals)"
    else:
        fear = "normal"
        fear_description = "Normal fear levels"

    if atr_percentile > 70:
        volatility = "high"
        volatility_description = "High volatility (wider stops, smaller sizing)"
    elif atr_percentile < 30:
        volatility = "low"
        volatility_description = "Low volatility (tighter stops, larger sizing)"
    else:
        volatility = "normal"
        volatility_description = "Normal volatility"

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

    corr_spy_qqq = get_correlation("SPY", "QQQ")
    corr_spy_tlt = get_correlation("SPY", "TLT")

    return {
        "trend": trend,
        "trend_description": trend_description,
        "fear": fear,
        "fear_description": fear_description,
        "volatility": volatility,
        "volatility_description": volatility_description,
        "adx": round(adx, 2),
        "vix_percentile": round(vix_percentile, 2),
        "atr_percentile": round(atr_percentile, 2),
        "breadth": breadth,
        "breadth_description": breadth_description,
        "strength": strength,
        "strength_description": strength_description,
        "advance_decline_ratio": round(adv_dec_ratio, 2),
        "nh_nl_ratio": round(nh_nl_ratio, 2),
        "correlation_spy_qqq": round(corr_spy_qqq, 2),
        "correlation_spy_tlt": round(corr_spy_tlt, 2),
    }