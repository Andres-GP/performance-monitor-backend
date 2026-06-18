# analytics/metrics.py
import numpy as np
from typing import List, Dict, Any

def calculate_win_rate(trades: List[Dict]) -> float:
    """Win rate over last N trades (default 50)"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades) * 100

def calculate_profit_factor(trades: List[Dict]) -> float:
    """Gross profit / Gross loss"""
    if not trades:
        return 0.0
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float('inf')

def calculate_max_drawdown(trades: List[Dict]) -> float:
    """Maximum drawdown from peak equity"""
    if not trades:
        return 0.0
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t.get("pnl", 0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd

def calculate_sharpe_ratio(trades: List[Dict], risk_free_rate: float = 0.02) -> float:
    """Sharpe ratio (annualized)"""
    if len(trades) < 2:
        return 0.0
    returns = [t.get("pnl", 0) for t in trades]
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    if std_return == 0:
        return 0.0
    return (mean_return - risk_free_rate / 252) / std_return * np.sqrt(252)

def calculate_consecutive_losses(trades: List[Dict]) -> int:
    """Maximum consecutive losing trades"""
    max_losses = 0
    current_losses = 0
    for t in trades:
        if t.get("pnl", 0) < 0:
            current_losses += 1
            max_losses = max(max_losses, current_losses)
        else:
            current_losses = 0
    return max_losses

def calculate_avg_win_loss_ratio(trades: List[Dict]) -> float:
    """Average win / Average loss"""
    wins = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
    losses = [abs(t["pnl"]) for t in trades if t.get("pnl", 0) < 0]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 1
    return avg_win / avg_loss if avg_loss > 0 else 0

def calculate_slippage(trades: List[Dict]) -> float:
    """Average slippage (difference between entry/exit price and expected)"""
    # Placeholder: require expected price data
    return 0.0

def calculate_adherence(trades: List[Dict], signals: int) -> float:
    """Percentage of signals executed vs signals generated"""
    if signals == 0:
        return 100.0
    return len(trades) / signals * 100