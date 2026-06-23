# tests/unit/test_metrics.py
import pytest
from app.analytics import metrics

def test_calculate_win_rate():
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": 0}, {"pnl": 50}]
    # 3 ganadores de 5 = 60%
    assert metrics.calculate_win_rate(trades) == 60.0

def test_calculate_win_rate_empty():
    assert metrics.calculate_win_rate([]) == 0.0

def test_calculate_profit_factor():
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
    # Gross profit = 300, Gross loss = 80 => 3.75
    assert metrics.calculate_profit_factor(trades) == 3.75

def test_calculate_profit_factor_no_losses():
    trades = [{"pnl": 10}, {"pnl": 20}]
    assert metrics.calculate_profit_factor(trades) == float('inf')

def test_calculate_max_drawdown():
    trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -80}, {"pnl": 30}]
    # Equity: 100,150,70,100; Peak=150, DD=(150-70)/150*100=53.33%
    result = metrics.calculate_max_drawdown(trades)
    assert round(result, 2) == 53.33

def test_calculate_sharpe_ratio_constant():
    trades = [{"pnl": 1} for _ in range(10)]
    # std=0 => Sharpe=0
    assert metrics.calculate_sharpe_ratio(trades) == 0.0

def test_calculate_consecutive_losses():
    trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": -3}, {"pnl": 2}, {"pnl": -1}]
    # Máxima racha: 2 (-5, -3)
    assert metrics.calculate_consecutive_losses(trades) == 2

def test_calculate_avg_win_loss_ratio():
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
    # Avg win = 150, Avg loss = 40 => 3.75
    assert metrics.calculate_avg_win_loss_ratio(trades) == 3.75