# analytics/edge.py
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

def calculate_oos_performance_ratio(actual_performance: float, expected_performance: float) -> float:
    """Calculate OOS/IS performance ratio."""
    if expected_performance == 0:
        return 0.0
    return actual_performance / expected_performance

def calculate_parameter_stability(parameters: List[Dict[str, Any]]) -> float:
    """
    Calculate parameter stability across walk-forward cycles.
    Lower coefficient of variation = more stable.
    """
    if not parameters:
        return 1.0
    
    # Extract a key parameter (e.g., Fast MA period)
    param_values = [p.get("fast", 0) for p in parameters if p.get("fast")]
    if len(param_values) < 2:
        return 1.0
    
    mean = np.mean(param_values)
    std = np.std(param_values)
    
    if mean == 0:
        return 1.0
    
    coefficient_of_variation = std / mean
    # Normalize: 0 = perfectly stable, 1 = very unstable
    return min(coefficient_of_variation, 1.0)

def calculate_skewness(trades: List[Dict]) -> float:
    """Calculate skewness of trade returns."""
    if len(trades) < 3:
        return 0.0
    returns = [t.get("pnl", 0) for t in trades]
    return float(pd.Series(returns).skew())

def calculate_kurtosis(trades: List[Dict]) -> float:
    """Calculate kurtosis of trade returns."""
    if len(trades) < 4:
        return 0.0
    returns = [t.get("pnl", 0) for t in trades]
    return float(pd.Series(returns).kurtosis())

def calculate_efficiency_ratio(is_performance: float, oos_performance: float) -> float:
    """Calculate efficiency ratio (OOS/IS)."""
    if is_performance == 0:
        return 0.0
    return oos_performance / is_performance

def calculate_walk_forward_win_rate(cycles: List[Dict]) -> float:
    """Percentage of walk-forward cycles with positive performance."""
    if not cycles:
        return 0.0
    positive = sum(1 for c in cycles if c.get("performance", 0) > 0)
    return (positive / len(cycles)) * 100

def calculate_oos_drawdown_ratio(is_dd: float, oos_dd: float) -> float:
    """Calculate OOS/IS drawdown ratio."""
    if is_dd == 0:
        return 1.0
    return oos_dd / is_dd

def get_edge_health_metrics(
    strategy_id: str,
    trades: List[Dict],
    backtest_performance: Optional[Dict] = None,
    walk_forward_cycles: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Calculate all edge health metrics for a strategy.
    """
    metrics = {
        "strategy_id": strategy_id,
        "timestamp": datetime.utcnow().isoformat(),
        "skewness": calculate_skewness(trades),
        "kurtosis": calculate_kurtosis(trades),
        "oos_performance_ratio": 0.0,
        "parameter_stability": 1.0,
        "efficiency_ratio": 0.0,
        "walk_forward_win_rate": 0.0,
        "oos_drawdown_ratio": 1.0,
        "edge_healthy": True,
        "alerts": []
    }
    
    if len(trades) < 10:
        metrics["alerts"].append("Insufficient trades for edge analysis")
        metrics["edge_healthy"] = False
        return metrics
    
    # Check skewness
    if metrics["skewness"] < -0.5:
        metrics["alerts"].append(f"Negative skewness detected: {metrics['skewness']:.2f}")
        metrics["edge_healthy"] = False
    
    # Check kurtosis (fat tails)
    if metrics["kurtosis"] > 3:
        metrics["alerts"].append(f"Excessive kurtosis (fat tails): {metrics['kurtosis']:.2f}")
    
    # If backtest data is available
    if backtest_performance:
        expected_perf = backtest_performance.get("expected_monthly_return", 0)
        actual_perf = calculate_recent_performance(trades, days=90)
        metrics["oos_performance_ratio"] = calculate_oos_performance_ratio(actual_perf, expected_perf)
        if metrics["oos_performance_ratio"] < 0.7:
            metrics["alerts"].append(f"OOS performance below 70% of IS: {metrics['oos_performance_ratio']:.2f}")
            metrics["edge_healthy"] = False
        
        expected_dd = backtest_performance.get("expected_max_drawdown", 100)
        actual_dd = calculate_recent_drawdown(trades, days=90)
        metrics["oos_drawdown_ratio"] = calculate_oos_drawdown_ratio(expected_dd, actual_dd)
        if metrics["oos_drawdown_ratio"] > 1.5:
            metrics["alerts"].append(f"OOS drawdown exceeds IS by 50%: {metrics['oos_drawdown_ratio']:.2f}")
            metrics["edge_healthy"] = False
    
    # If walk-forward cycles are available
    if walk_forward_cycles:
        metrics["walk_forward_win_rate"] = calculate_walk_forward_win_rate(walk_forward_cycles)
        if metrics["walk_forward_win_rate"] < 70:
            metrics["alerts"].append(f"Walk-forward win rate below 70%: {metrics['walk_forward_win_rate']:.1f}%")
            metrics["edge_healthy"] = False
        
        metrics["parameter_stability"] = calculate_parameter_stability(walk_forward_cycles)
        if metrics["parameter_stability"] > 0.5:
            metrics["alerts"].append(f"Parameter instability detected: {metrics['parameter_stability']:.2f}")
            metrics["edge_healthy"] = False
    
    return metrics

def calculate_recent_performance(trades: List[Dict], days: int = 90) -> float:
    """Calculate total PnL over last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent_trades = [
        t for t in trades 
        if t.get("exit_time") and datetime.fromisoformat(t["exit_time"].replace('Z', '+00:00')) > cutoff
    ]
    return sum(t.get("pnl", 0) for t in recent_trades)

def calculate_recent_drawdown(trades: List[Dict], days: int = 90) -> float:
    """Calculate max drawdown over last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent_trades = [
        t for t in trades 
        if t.get("exit_time") and datetime.fromisoformat(t["exit_time"].replace('Z', '+00:00')) > cutoff
    ]
    if not recent_trades:
        return 0.0
    
    equity = 0
    peak = 0
    max_dd = 0
    for t in recent_trades:
        equity += t.get("pnl", 0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd