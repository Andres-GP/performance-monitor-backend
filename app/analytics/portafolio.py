# analytics/portfolio.py
import numpy as np
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime, timedelta

def calculate_portfolio_correlation(strategies_trades: Dict[str, List[Dict]], window_days: int = 90) -> Dict[str, float]:
    """
    Calculate correlation between strategies' PnL over the last N days.
    Returns a matrix of correlations.
    """
    # Create daily PnL series for each strategy
    daily_pnl = {}
    for strategy_id, trades in strategies_trades.items():
        if len(trades) < 2:
            continue
        # Convert trades to daily PnL
        pnl_by_day = {}
        for trade in trades:
            if trade.get("exit_time"):
                date = datetime.fromisoformat(trade["exit_time"].replace('Z', '+00:00')).date()
                pnl_by_day[date] = pnl_by_day.get(date, 0) + trade.get("pnl", 0)
        daily_pnl[strategy_id] = pd.Series(pnl_by_day)
    
    if len(daily_pnl) < 2:
        return {}
    
    # Align all series to same date range
    df = pd.DataFrame(daily_pnl).fillna(0)
    
    # Calculate correlation matrix
    corr_matrix = df.corr()
    
    # Return only significant correlations (>0.7)
    correlations = {}
    for i in range(len(corr_matrix.columns)):
        for j in range(i+1, len(corr_matrix.columns)):
            col_i = corr_matrix.columns[i]
            col_j = corr_matrix.columns[j]
            corr_value = corr_matrix.iloc[i, j]
            if abs(corr_value) > 0.7:
                correlations[f"{col_i}_{col_j}"] = corr_value
    
    return correlations

def calculate_portfolio_drawdown(strategies_trades: Dict[str, List[Dict]]) -> Dict[str, float]:
    """
    Calculate combined portfolio drawdown from peak equity.
    """
    # Combine all trades into a single PnL series
    all_trades = []
    for trades in strategies_trades.values():
        all_trades.extend(trades)
    
    if not all_trades:
        return {"max_drawdown": 0, "current_drawdown": 0}
    
    # Sort trades by exit time
    all_trades.sort(key=lambda x: x.get("exit_time", ""))
    
    equity = 0
    peak = 0
    max_dd = 0
    for trade in all_trades:
        equity += trade.get("pnl", 0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    
    current_dd = (peak - equity) / peak * 100 if peak > 0 else 0
    
    return {"max_drawdown": max_dd, "current_drawdown": current_dd}

def calculate_portfolio_sharpe(strategies_trades: Dict[str, List[Dict]], risk_free_rate: float = 0.02) -> float:
    """
    Calculate combined portfolio Sharpe ratio (annualized).
    """
    all_trades = []
    for trades in strategies_trades.values():
        all_trades.extend(trades)
    
    if len(all_trades) < 2:
        return 0.0
    
    returns = [t.get("pnl", 0) for t in all_trades]
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    if std_return == 0:
        return 0.0
    
    # Annualize (assuming daily trades)
    return (mean_return - risk_free_rate / 252) / std_return * np.sqrt(252)

def calculate_exposure_by_category(strategies: List[Dict]) -> Dict[str, float]:
    """
    Calculate capital exposure by category (instrument_type, etc.).
    """
    if not strategies:
        return {}
    
    total_capital = sum(s.get("sizing", 0) for s in strategies)
    if total_capital == 0:
        return {}
    
    exposure = {}
    for strategy in strategies:
        category = strategy.get("instrument_type", "Unknown")
        capital = strategy.get("sizing", 0)
        exposure[category] = exposure.get(category, 0) + capital
    
    # Convert to percentages
    for key in exposure:
        exposure[key] = (exposure[key] / total_capital) * 100
    
    return exposure

def calculate_ruin_probability(strategies_trades: Dict[str, List[Dict]], capital: float, max_loss_threshold: float = 0.5) -> float:
    """
    Monte Carlo simulation of ruin probability.
    """
    # Simplified: estimate based on historical drawdown and Sharpe
    # Full Monte Carlo would be more accurate but requires more data
    return 0.0  # Placeholder

def calculate_total_transaction_costs(strategies_trades: Dict[str, List[Dict]]) -> float:
    """
    Calculate total transaction costs as % of capital.
    """
    # This requires cost data per trade (commissions, slippage)
    # For now, return placeholder
    return 0.0