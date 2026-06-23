import pytest
from unittest.mock import patch, MagicMock
from app.analytics import regime

def test_get_regime_summary():
    summary = regime.get_regime_summary(adx=25.0, vix_percentile=50.0, atr_percentile=50.0)
    assert "trend" in summary
    assert "fear" in summary
    assert "volatility" in summary
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

def test_get_adx_fallback(mocker):
    mocker.patch('app.analytics.regime.yf.download', side_effect=Exception("Error"))
    assert regime.get_adx() == 25.0

def test_get_adx_with_data(mocker):
    mock_data = MagicMock()
    mock_data.empty = False
    mock_data['High'] = [100, 101, 102]
    mock_data['Low'] = [99, 100, 101]
    mock_data['Close'] = [100, 101, 102]
    mocker.patch('app.analytics.regime.yf.download', return_value=mock_data)
    assert regime.get_adx() == 25.0

def test_get_vix_percentile_fallback(mocker):
    mocker.patch('app.analytics.regime.yf.download', side_effect=Exception("Error"))
    assert regime.get_vix_percentile() == 50.0

def test_get_atr_percentile_fallback(mocker):
    mocker.patch('app.analytics.regime.yf.download', side_effect=Exception("Error"))
    assert regime.get_atr_percentile() == 50.0

def test_get_correlation_fallback(mocker):
    with patch('app.analytics.regime.get_correlation', return_value=0.0):
        result = regime.get_correlation("SPY", "QQQ")
        assert result == 0.0

def test_get_regime_summary_all_cases():
    summary = regime.get_regime_summary(adx=10, vix_percentile=90, atr_percentile=80)
    assert summary["trend"] == "sideways"
    assert summary["fear"] == "extreme_fear"
    assert summary["volatility"] == "high"

    summary = regime.get_regime_summary(adx=30, vix_percentile=10, atr_percentile=20)
    assert summary["trend"] == "trending"
    assert summary["fear"] == "extreme_complacency"
    assert summary["volatility"] == "low"