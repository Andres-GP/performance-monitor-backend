# tests/unit/test_edge.py
import pytest
from datetime import datetime, timedelta
from app.analytics import edge

def test_calculate_skewness():
    trades = [{"pnl": 1}, {"pnl": 2}, {"pnl": 3}, {"pnl": 4}, {"pnl": 100}]
    skew = edge.calculate_skewness(trades)
    assert skew > 0  # cola positiva

def test_calculate_skewness_insufficient():
    trades = [{"pnl": 1}, {"pnl": 2}]
    assert edge.calculate_skewness(trades) == 0.0

def test_calculate_efficiency_ratio():
    assert edge.calculate_efficiency_ratio(100, 80) == 0.8
    assert edge.calculate_efficiency_ratio(0, 50) == 0.0

def test_calculate_walk_forward_win_rate():
    cycles = [{"performance": 10}, {"performance": -5}, {"performance": 20}, {"performance": 0}]
    # 2 positivos de 4 = 50%
    assert edge.calculate_walk_forward_win_rate(cycles) == 50.0

def test_calculate_parameter_stability():
    params = [{"fast": 10}, {"fast": 12}, {"fast": 11}]
    stab = edge.calculate_parameter_stability(params)
    # CV ~ (std=0.816, mean=11) => 0.074
    assert 0.07 < stab < 0.08

# ==================== TESTS ADICIONALES ====================

def test_calculate_oos_performance_ratio():
    assert edge.calculate_oos_performance_ratio(80, 100) == 0.8
    assert edge.calculate_oos_performance_ratio(0, 100) == 0.0
    assert edge.calculate_oos_performance_ratio(50, 0) == 0.0  # expected=0

def test_calculate_kurtosis():
    trades = [{"pnl": 1}, {"pnl": 2}, {"pnl": 3}, {"pnl": 4}, {"pnl": 10}]
    kurt = edge.calculate_kurtosis(trades)
    assert isinstance(kurt, float)

def test_calculate_kurtosis_insufficient():
    trades = [{"pnl": 1}, {"pnl": 2}, {"pnl": 3}]  # menos de 4
    assert edge.calculate_kurtosis(trades) == 0.0

def test_calculate_recent_performance():
    trades = [
        {"pnl": 100, "exit_time": (datetime.utcnow() - timedelta(days=10)).isoformat()},
        {"pnl": 50, "exit_time": (datetime.utcnow() - timedelta(days=50)).isoformat()},
        {"pnl": 200, "exit_time": (datetime.utcnow() - timedelta(days=80)).isoformat()}
    ]
    # Últimos 30 días: solo el primero (100)
    perf = edge.calculate_recent_performance(trades, days=30)
    assert perf == 100

def test_calculate_recent_drawdown():
    trades = [
        {"pnl": 100, "exit_time": (datetime.utcnow() - timedelta(days=10)).isoformat()},
        {"pnl": -50, "exit_time": (datetime.utcnow() - timedelta(days=20)).isoformat()},
        {"pnl": -30, "exit_time": (datetime.utcnow() - timedelta(days=30)).isoformat()}
    ]
    dd = edge.calculate_recent_drawdown(trades, days=40)
    assert dd > 0

def test_get_edge_health_metrics():
    trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": 15}, {"pnl": -10}] * 10  # 50 trades
    backtest = {"expected_monthly_return": 100, "expected_max_drawdown": 10}
    cycles = [{"performance": 10}, {"performance": 20}, {"performance": -5}]
    
    metrics = edge.get_edge_health_metrics("s1", trades, backtest, cycles)
    assert metrics["strategy_id"] == "s1"
    assert "skewness" in metrics
    assert "kurtosis" in metrics
    assert "edge_healthy" in metrics