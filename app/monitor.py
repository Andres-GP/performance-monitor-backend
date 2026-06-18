# monitor.py
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from supabase import Client
from .analytics import metrics, regime, edge
from .api import send_alert_email
from .utils.logger import setup_logger

logger = setup_logger(__name__)

class PerformanceMonitor:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.thresholds = {
            "win_rate": {"min": 40, "expected": 60},
            "profit_factor": {"min": 1.2, "expected": 1.5},
            "max_drawdown": {"max": 12, "critical": 20},
            "sharpe_ratio": {"min": 0.8, "expected": 1.5},
            "consecutive_losses": {"max": 10},
            "avg_win_loss_ratio": {"min_change": -30},
            "adherence": {"min": 90},
            "slippage": {"max": 2},
            "portfolio": {
                "max_correlation": 0.7,
                "max_drawdown_global": 15,
                "critical_drawdown_global": 20,
                "sharpe_min": 1.0,
                "concentration_max": 30,
                "ruin_probability_max": 0.01,
                "transaction_cost_max": 2.0,
            },
            "edge": {
                "oos_degradation_max": 30,
                "efficiency_ratio_min": 0.5,
                "walk_forward_win_rate_min": 70,
                "oos_drawdown_ratio_max": 1.5,
                "skewness_min": -0.5,
            }
        }

    # ======================== DAILY CHECK ========================
    async def run_daily_check(self):
        logger.info("Running daily performance check...")
        strategies = self.supabase.table("strategies").select("*").eq("state", "Running").execute()
        for strategy in strategies.data:
            await self.check_strategy_performance(strategy)
        logger.info("Daily performance check completed")

    async def check_strategy_performance(self, strategy: Dict):
        strategy_id = strategy["strategy_id"]
        strategy_name = strategy.get("name", strategy_id)
        logger.info(f"Checking strategy: {strategy_name} ({strategy_id})")

        trades = self.supabase.table("trades").select("*").eq("strategy_id", strategy_id).order("exit_time", desc=True).limit(50).execute()
        trades_data = trades.data

        if len(trades_data) < 10:
            logger.info(f"Strategy {strategy_id}: insufficient trades ({len(trades_data)}) for analysis")
            return

        win_rate = metrics.calculate_win_rate(trades_data)
        profit_factor = metrics.calculate_profit_factor(trades_data)
        max_dd = metrics.calculate_max_drawdown(trades_data)
        sharpe = metrics.calculate_sharpe_ratio(trades_data)
        consecutive_losses = metrics.calculate_consecutive_losses(trades_data)
        avg_win_loss = metrics.calculate_avg_win_loss_ratio(trades_data)

        logger.info(f"Strategy {strategy_id}: WR={win_rate:.1f}%, PF={profit_factor:.2f}, DD={max_dd:.1f}%, Sharpe={sharpe:.2f}")

        alerts = []
        if win_rate < self.thresholds["win_rate"]["min"]:
            alerts.append(f"Win rate {win_rate:.1f}% below threshold ({self.thresholds['win_rate']['min']}%)")
        if profit_factor < self.thresholds["profit_factor"]["min"]:
            alerts.append(f"Profit factor {profit_factor:.2f} below threshold ({self.thresholds['profit_factor']['min']})")
        if max_dd > self.thresholds["max_drawdown"]["max"]:
            alerts.append(f"Drawdown {max_dd:.1f}% exceeds threshold ({self.thresholds['max_drawdown']['max']}%)")
            if max_dd > self.thresholds["max_drawdown"]["critical"]:
                alerts.append(f"CRITICAL: Drawdown {max_dd:.1f}% exceeds critical limit ({self.thresholds['max_drawdown']['critical']}%)")
        if sharpe < self.thresholds["sharpe_ratio"]["min"]:
            alerts.append(f"Sharpe ratio {sharpe:.2f} below threshold ({self.thresholds['sharpe_ratio']['min']})")
        if consecutive_losses > self.thresholds["consecutive_losses"]["max"]:
            alerts.append(f"Consecutive losses {consecutive_losses} exceeds threshold ({self.thresholds['consecutive_losses']['max']})")

        if alerts:
            subject = f"[Performance Monitor] {strategy_name} - Performance Alerts"
            body = f"Strategy: {strategy_name}\n\n" + "\n".join(alerts) + f"\n\nTimestamp: {datetime.utcnow().isoformat()}"
            send_alert_email(subject, body)
            self.supabase.table("strategies").update({"health_status": "unhealthy"}).eq("strategy_id", strategy_id).execute()
            logger.warning(f"Strategy {strategy_id} marked as unhealthy due to {len(alerts)} alerts")
        else:
            self.supabase.table("strategies").update({"health_status": "healthy"}).eq("strategy_id", strategy_id).execute()

        try:
            self.supabase.table("performance_metrics").insert({
                "strategy_id": strategy_id,
                "date": datetime.utcnow().date().isoformat(),
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "max_drawdown": max_dd,
                "sharpe_ratio": sharpe,
                "consecutive_losses": consecutive_losses,
                "avg_win_loss_ratio": avg_win_loss,
            }).execute()
        except Exception as e:
            logger.error(f"Failed to store performance metrics for {strategy_id}: {e}")

    # ======================== WEEKLY CHECK (REGIME) ========================
    async def run_weekly_check(self):
        logger.info("Running weekly regime check...")
        await self.check_market_regime()
        logger.info("Weekly regime check completed")

    async def check_market_regime(self):
        logger.info("Checking market regime...")
        try:
            adx = regime.get_adx(symbol="SPY", period=14)
            vix_percentile = regime.get_vix_percentile()
            atr_percentile = regime.get_atr_percentile(symbol="SPY", period=14)
            regime_summary = regime.get_regime_summary(adx, vix_percentile, atr_percentile)
            logger.info(f"Regime summary: {regime_summary}")
            self.supabase.table("market_regime").insert({
                "date": datetime.utcnow().date().isoformat(),
                "trend": regime_summary.get("trend"),
                "fear": regime_summary.get("fear"),
                "volatility": regime_summary.get("volatility"),
                "adx": regime_summary.get("adx"),
                "vix_percentile": regime_summary.get("vix_percentile"),
                "atr_percentile": regime_summary.get("atr_percentile"),
            }).execute()
            if regime_summary.get("fear") in ["extreme_fear", "extreme_complacency"]:
                send_alert_email(
                    "[Performance Monitor] Extreme Market Regime Detected",
                    f"Market regime: {regime_summary}\nConsider adjusting sizing or directional bias."
                )
        except Exception as e:
            logger.error(f"Error checking market regime: {e}")

    # ======================== MONTHLY CHECK (EDGE HEALTH & PORTFOLIO) ========================
    async def run_monthly_check(self):
        logger.info("Running monthly edge health check...")
        await self.check_edge_health()
        await self.check_portfolio_metrics()
        logger.info("Monthly edge health check completed")

    async def check_edge_health(self):
        logger.info("Checking edge health...")
        strategies = self.supabase.table("strategies").select("strategy_id", "name").eq("state", "Running").execute()
        for strategy in strategies.data:
            strategy_id = strategy["strategy_id"]
            strategy_name = strategy.get("name", strategy_id)
            
            backtest = self.supabase.table("backtest_data").select("*").eq("strategy_id", strategy_id).order("period_start", desc=True).limit(1).execute()
            if not backtest.data:
                logger.info(f"No backtest data for {strategy_name}, skipping edge check")
                continue
            bt_data = backtest.data[0]
            expected_pnl = bt_data.get("expected_pnl")
            if not expected_pnl:
                logger.info(f"No expected_pnl for {strategy_name}, skipping")
                continue
            
            three_months_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
            trades = self.supabase.table("trades").select("*").eq("strategy_id", strategy_id).gte("exit_time", three_months_ago).execute()
            trades_data = trades.data
            if len(trades_data) < 10:
                logger.info(f"Insufficient trades for OOS analysis: {len(trades_data)}")
                continue
            
            oos_pnl = sum(t["pnl"] for t in trades_data)
            oos_degradation = (expected_pnl - oos_pnl) / expected_pnl * 100 if expected_pnl > 0 else 0
            efficiency_ratio = oos_pnl / expected_pnl if expected_pnl > 0 else 0
            
            alerts = []
            if oos_degradation > self.thresholds["edge"]["oos_degradation_max"]:
                alerts.append(f"OOS degradation: {oos_degradation:.1f}% (threshold: {self.thresholds['edge']['oos_degradation_max']}%)")
            if efficiency_ratio < self.thresholds["edge"]["efficiency_ratio_min"]:
                alerts.append(f"Efficiency ratio: {efficiency_ratio:.2f} (threshold: {self.thresholds['edge']['efficiency_ratio_min']})")
            
            returns = [t["pnl"] for t in trades_data]
            if len(returns) >= 3:
                skewness = edge.calculate_distribution_skewness(trades_data)
                if skewness < self.thresholds["edge"]["skewness_min"]:
                    alerts.append(f"Negative skewness: {skewness:.2f} (threshold: {self.thresholds['edge']['skewness_min']})")
            else:
                skewness = None
            
            win_rate = metrics.calculate_win_rate(trades_data)
            if win_rate < self.thresholds["edge"]["walk_forward_win_rate_min"]:
                alerts.append(f"Walk-forward win rate: {win_rate:.1f}% (threshold: {self.thresholds['edge']['walk_forward_win_rate_min']}%)")
            
            # Save edge metrics
            edge_record = {
                "strategy_id": strategy_id,
                "date": datetime.utcnow().date().isoformat(),
                "oos_degradation": oos_degradation,
                "efficiency_ratio": efficiency_ratio,
                "walk_forward_win_rate": win_rate,
                "oos_drawdown_ratio": None,  # Placeholder
                "skewness": skewness,
                "health_status": "decay" if alerts else "healthy"
            }
            try:
                self.supabase.table("edge_metrics").insert(edge_record).execute()
            except Exception as e:
                logger.error(f"Failed to store edge metrics for {strategy_id}: {e}")
            
            if alerts:
                subject = f"[Performance Monitor] {strategy_name} - Edge Decay Detected"
                body = f"Strategy: {strategy_name}\n\n" + "\n".join(alerts) + f"\n\nTimestamp: {datetime.utcnow().isoformat()}"
                send_alert_email(subject, body)
                self.supabase.table("strategies").update({"health_status": "edge_decay"}).eq("strategy_id", strategy_id).execute()
                logger.warning(f"Strategy {strategy_id} marked as edge_decay")
            else:
                logger.info(f"Strategy {strategy_id}: edge health OK")

    async def check_portfolio_metrics(self):
        logger.info("Checking portfolio-level metrics...")
        strategies = self.supabase.table("strategies").select("strategy_id", "name", "instrument_type").eq("state", "Running").execute()
        if len(strategies.data) < 2:
            logger.info("Less than 2 active strategies, skipping portfolio analysis")
            return
        
        three_months_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
        all_trades = self.supabase.table("trades").select("*").gte("exit_time", three_months_ago).execute()
        trades_data = all_trades.data
        if len(trades_data) < 10:
            logger.info("Insufficient portfolio trades for analysis")
            return
        
        df = pd.DataFrame(trades_data)
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['date'] = df['exit_time'].dt.date
        df['pnl'] = df['pnl'].astype(float)
        pivot = df.pivot_table(index='date', columns='strategy_id', values='pnl', aggfunc='sum', fill_value=0)
        if len(pivot.columns) < 2:
            logger.info("Not enough data for correlation analysis")
            return
        
        alerts = []
        # Correlation
        corr_matrix = pivot.corr()
        for i in range(len(corr_matrix.columns)):
            for j in range(i+1, len(corr_matrix.columns)):
                corr_val = corr_matrix.iloc[i, j]
                if corr_val > self.thresholds["portfolio"]["max_correlation"]:
                    strategy_a = corr_matrix.columns[i]
                    strategy_b = corr_matrix.columns[j]
                    alerts.append(f"High correlation between {strategy_a} and {strategy_b}: {corr_val:.2f} (threshold: {self.thresholds['portfolio']['max_correlation']})")
        
        # Portfolio drawdown
        portfolio_equity = pivot.sum(axis=1).cumsum()
        if len(portfolio_equity) > 0:
            peak = portfolio_equity.cummax()
            drawdown = (peak - portfolio_equity) / peak * 100
            max_dd = drawdown.max()
            if max_dd > self.thresholds["portfolio"]["max_drawdown_global"]:
                alerts.append(f"Portfolio max drawdown: {max_dd:.1f}% (threshold: {self.thresholds['portfolio']['max_drawdown_global']}%)")
                if max_dd > self.thresholds["portfolio"]["critical_drawdown_global"]:
                    alerts.append(f"CRITICAL: Portfolio drawdown {max_dd:.1f}% exceeds critical limit ({self.thresholds['portfolio']['critical_drawdown_global']}%)")
        
        # Portfolio Sharpe
        daily_returns = pivot.sum(axis=1).values
        if len(daily_returns) > 0:
            sharpe = (np.mean(daily_returns) / (np.std(daily_returns) + 1e-6)) * np.sqrt(252) if np.std(daily_returns) > 0 else 0
            if sharpe < self.thresholds["portfolio"]["sharpe_min"]:
                alerts.append(f"Portfolio Sharpe ratio: {sharpe:.2f} (threshold: {self.thresholds['portfolio']['sharpe_min']})")
        
        # Exposure by category
        strategies_dict = {s["strategy_id"]: s for s in strategies.data}
        category_exposure = {}
        for strategy_id in pivot.columns:
            strategy = strategies_dict.get(strategy_id)
            if strategy:
                category = strategy.get("instrument_type", "Unknown")
                total_pnl = pivot[strategy_id].sum()
                category_exposure[category] = category_exposure.get(category, 0) + abs(total_pnl)
        total_exposure = sum(category_exposure.values())
        if total_exposure > 0:
            for category, exposure in category_exposure.items():
                percentage = exposure / total_exposure * 100
                if percentage > self.thresholds["portfolio"]["concentration_max"]:
                    alerts.append(f"Concentration in {category}: {percentage:.1f}% (threshold: {self.thresholds['portfolio']['concentration_max']}%)")
        
        # Ruin probability (simplified Monte Carlo)
        if len(daily_returns) > 10:
            np.random.seed(42)
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            n_simulations = 1000
            n_days = 252
            simulations = np.random.normal(mean_ret, std_ret, (n_simulations, n_days))
            final_equity = np.cumsum(simulations, axis=1)
            max_loss = final_equity.min(axis=1)
            # Assuming initial capital of 100,000 (you can make this configurable)
            initial_capital = 100000
            ruin_count = np.sum(max_loss < -0.4 * initial_capital)
            ruin_prob = ruin_count / n_simulations * 100
            if ruin_prob > self.thresholds["portfolio"]["ruin_probability_max"] * 100:
                alerts.append(f"Ruin probability: {ruin_prob:.2f}% (threshold: {self.thresholds['portfolio']['ruin_probability_max']*100}%)")
        
        if alerts:
            subject = "[Performance Monitor] Portfolio Alerts"
            body = "Portfolio-level alerts:\n\n" + "\n".join(alerts) + f"\n\nTimestamp: {datetime.utcnow().isoformat()}"
            send_alert_email(subject, body)
            logger.warning(f"Portfolio alerts: {len(alerts)}")
        else:
            logger.info("Portfolio metrics OK")