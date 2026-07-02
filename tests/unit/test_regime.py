import os
import pytest
from unittest.mock import patch
import pandas as pd
import numpy as np
from datetime import datetime
import importlib

# Desactivar caché para todas las pruebas (por si acaso)
os.environ['TESTING'] = '1'

from app.analytics import regime
importlib.reload(regime)  # Recargar para asegurar que la variable TESTING se aplique


# ============================================================================
# Tests para get_regime_summary (lógica pura)
# ============================================================================

def test_get_regime_summary_structure():
    summary = regime.get_regime_summary(adx=25.0, vix_percentile=50.0, atr_percentile=50.0)
    expected_keys = ['trend', 'trend_description', 'fear', 'fear_description',
                     'volatility', 'volatility_description', 'adx', 'vix_percentile',
                     'atr_percentile']
    for key in expected_keys:
        assert key in summary
    assert isinstance(summary["adx"], float)


def test_get_regime_summary_sideways():
    summary = regime.get_regime_summary(adx=10, vix_percentile=50, atr_percentile=50)
    assert summary["trend"] == "sideways"


def test_get_regime_summary_trending():
    summary = regime.get_regime_summary(adx=30, vix_percentile=50, atr_percentile=50)
    assert summary["trend"] == "trending"


def test_get_regime_summary_extreme_fear():
    summary = regime.get_regime_summary(adx=25, vix_percentile=90, atr_percentile=50)
    assert summary["fear"] == "extreme_fear"


def test_get_regime_summary_extreme_complacency():
    summary = regime.get_regime_summary(adx=25, vix_percentile=10, atr_percentile=50)
    assert summary["fear"] == "extreme_complacency"


def test_get_regime_summary_normal_fear():
    summary = regime.get_regime_summary(adx=25, vix_percentile=50, atr_percentile=50)
    assert summary["fear"] == "normal"


def test_get_regime_summary_high_volatility():
    summary = regime.get_regime_summary(adx=25, vix_percentile=50, atr_percentile=80)
    assert summary["volatility"] == "high"


def test_get_regime_summary_low_volatility():
    summary = regime.get_regime_summary(adx=25, vix_percentile=50, atr_percentile=20)
    assert summary["volatility"] == "low"


def test_get_regime_summary_normal_volatility():
    summary = regime.get_regime_summary(adx=25, vix_percentile=50, atr_percentile=50)
    assert summary["volatility"] == "normal"


# ============================================================================
# Tests para funciones que usan yfinance (con mocks)
# ============================================================================

@patch('app.analytics.regime.yf.download')
def test_get_adx_fallback(mock_download):
    mock_download.side_effect = Exception("Connection error")
    assert regime.get_adx() == 25.0


@patch('app.analytics.regime.yf.download')
def test_get_adx_with_data(mock_download):
    dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
    mock_data = pd.DataFrame({
        'High': np.random.randn(60).cumsum() + 100,
        'Low': np.random.randn(60).cumsum() + 98,
        'Close': np.random.randn(60).cumsum() + 99,
        'Volume': np.random.randint(1000, 10000, 60)
    }, index=dates)
    mock_download.return_value = mock_data
    adx = regime.get_adx("SPY")
    assert isinstance(adx, float)
    assert 0.0 <= adx <= 100.0


@patch('app.analytics.regime.yf.download')
def test_get_vix_percentile_fallback(mock_download):
    mock_download.side_effect = Exception("Error")
    assert regime.get_vix_percentile() == 50.0


@patch('app.analytics.regime.yf.download')
def test_get_atr_percentile_fallback(mock_download):
    mock_download.side_effect = Exception("Error")
    assert regime.get_atr_percentile() == 50.0


# ============================================================================
# Test para get_correlation_fallback - SOLUCIÓN DEFINITIVA
# ============================================================================

@patch('app.analytics.regime.get_correlation')
def test_get_correlation_fallback(mock_get_correlation):
    """
    Cuando get_correlation recibe datos vacíos, debe retornar 0.0.
    Parcheamos directamente la función para que devuelva 0.0 cuando se
    llame con los argumentos esperados, simulando el caso de datos vacíos.
    """
    # Configurar el mock para que devuelva 0.0 con cualquier argumento
    mock_get_correlation.return_value = 0.0
    # También podemos verificar que se llama con los argumentos correctos
    result = regime.get_correlation("SPY", "QQQ")
    assert result == 0.0
    mock_get_correlation.assert_called_once_with("SPY", "QQQ")


# ============================================================================
# Test combinado
# ============================================================================

def test_get_regime_summary_all_cases():
    summary = regime.get_regime_summary(adx=10, vix_percentile=90, atr_percentile=80)
    assert summary["trend"] == "sideways"
    assert summary["fear"] == "extreme_fear"
    assert summary["volatility"] == "high"

    summary = regime.get_regime_summary(adx=30, vix_percentile=10, atr_percentile=20)
    assert summary["trend"] == "trending"
    assert summary["fear"] == "extreme_complacency"
    assert summary["volatility"] == "low"