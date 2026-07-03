import asyncio
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any
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
                "transaction_cost_gross_max": 20.0,
                "allocation_deviation_max": 20.0,
                "market_impact_max": 2.0,
            },
            "edge": {
                "oos_degradation_max": 30,
                "efficiency_ratio_min": 0.5,
                "walk_forward_win_rate_min": 70,
                "oos_drawdown_ratio_max": 1.5,
                "skewness_min": -0.5,
            }
        }

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

            record = {
                "date": datetime.utcnow().date().isoformat(),
                "trend": regime_summary.get("trend"),
                "fear": regime_summary.get("fear"),
                "volatility": regime_summary.get("volatility"),
                "adx": regime_summary.get("adx"),
                "vix_percentile": regime_summary.get("vix_percentile"),
                "atr_percentile": regime_summary.get("atr_percentile"),
                "breadth": regime_summary.get("breadth"),
                "strength": regime_summary.get("strength"),
                "advance_decline_ratio": regime_summary.get("advance_decline_ratio"),
                "nh_nl_ratio": regime_summary.get("nh_nl_ratio"),
                "correlation_spy_qqq": regime_summary.get("correlation_spy_qqq"),
                "correlation_spy_tlt": regime_summary.get("correlation_spy_tlt"),
            }
            self.supabase.table("market_regime").insert(record).execute()

            if regime_summary.get("fear") in ["extreme_fear", "extreme_complacency"]:
                send_alert_email(
                    "[Performance Monitor] Extreme Market Regime Detected",
                    f"Market regime: {regime_summary}\nConsider adjusting sizing or directional bias."
                )
        except Exception as e:
            logger.error(f"Error checking market regime: {e}")

    async def run_monthly_check(self):
        logger.info("Running monthly edge health and portfolio check...")
        await self.check_edge_health()
        await self.run_portfolio_check()
        logger.info("Monthly check completed")

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

            edge_record = {
                "strategy_id": strategy_id,
                "date": datetime.utcnow().date().isoformat(),
                "oos_degradation": oos_degradation,
                "efficiency_ratio": efficiency_ratio,
                "walk_forward_win_rate": win_rate,
                "oos_drawdown_ratio": None,
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

    async def run_portfolio_check(self):
        logger.info("Running portfolio metrics update...")
        await self.check_portfolio_metrics()
        logger.info("Portfolio metrics update completed")

    async def check_portfolio_metrics(self):
        logger.info("Checking portfolio-level metrics...")
        strategies = self.supabase.table("strategies").select("*").eq("state", "Running").execute()

        if len(strategies.data) < 1:
            logger.info("No active strategies, skipping portfolio analysis")
            return

        initial_capital = 100000
        capital_result = self.supabase.table("accounts").select("capital").execute()
        if capital_result.data:
            try:
                initial_capital = sum(float(acc.get("capital", 0)) for acc in capital_result.data)
            except Exception as e:
                logger.warning(f"Error parsing capital data: {e}, using default 100000")
                initial_capital = 100000
            if initial_capital == 0:
                initial_capital = 100000
                logger.warning("Capital sum is zero, using default 100000")
        else:
            logger.warning("No capital data found, using default 100000")

        three_months_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
        one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        all_trades = self.supabase.table("trades").select("*").gte("exit_time", three_months_ago).execute()
        trades_data = all_trades.data
        if len(trades_data) < 5:
            logger.info("Insufficient portfolio trades for analysis")
            return

        df = pd.DataFrame(trades_data)
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['date'] = df['exit_time'].dt.date
        df['pnl'] = df['pnl'].astype(float)
        df['cost'] = df.get('cost', 0).astype(float).fillna(0)
        pivot = df.pivot_table(index='date', columns='strategy_id', values='pnl', aggfunc='sum', fill_value=0)

        alerts = []
        correlation_matrix = {}
        concentration_metrics = {}
        allocation_deviations = {}
        exposure_data = {}
        sharpe = 0
        max_dd = 0
        current_dd = 0
        ruin_prob = 0

        if len(pivot.columns) >= 2:
            corr_matrix = pivot.corr()
            correlation_matrix = corr_matrix.to_dict()
            for i in range(len(corr_matrix.columns)):
                for j in range(i+1, len(corr_matrix.columns)):
                    corr_val = corr_matrix.iloc[i, j]
                    if corr_val > self.thresholds["portfolio"]["max_correlation"]:
                        strategy_a = corr_matrix.columns[i]
                        strategy_b = corr_matrix.columns[j]
                        alerts.append(f"High correlation between {strategy_a} and {strategy_b}: {corr_val:.2f} (threshold: {self.thresholds['portfolio']['max_correlation']})")
        else:
            correlation_matrix = {"note": "Only one strategy, no correlation calculated"}

        portfolio_equity = pivot.sum(axis=1).cumsum()
        if len(portfolio_equity) > 0:
            peak = portfolio_equity.cummax()
            drawdown_series = (peak - portfolio_equity) / peak * 100
            max_dd = drawdown_series.max()
            current_dd = drawdown_series.iloc[-1] if len(drawdown_series) > 0 else 0
            if max_dd > self.thresholds["portfolio"]["max_drawdown_global"]:
                alerts.append(f"Portfolio max drawdown: {max_dd:.1f}% (threshold: {self.thresholds['portfolio']['max_drawdown_global']}%)")
                if max_dd > self.thresholds["portfolio"]["critical_drawdown_global"]:
                    alerts.append(f"CRITICAL: Portfolio drawdown {max_dd:.1f}% exceeds critical limit ({self.thresholds['portfolio']['critical_drawdown_global']}%)")

        daily_returns = pivot.sum(axis=1).values
        if len(daily_returns) > 0:
            sharpe = (np.mean(daily_returns) / (np.std(daily_returns) + 1e-6)) * np.sqrt(252) if np.std(daily_returns) > 0 else 0
            if sharpe < self.thresholds["portfolio"]["sharpe_min"]:
                alerts.append(f"Portfolio Sharpe ratio: {sharpe:.2f} (threshold: {self.thresholds['portfolio']['sharpe_min']})")

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
                exposure_data[category] = round(percentage, 2)
                if percentage > self.thresholds["portfolio"]["concentration_max"]:
                    alerts.append(f"Concentration in {category}: {percentage:.1f}% (threshold: {self.thresholds['portfolio']['concentration_max']}%)")
                    concentration_metrics[category] = round(percentage, 2)

        if len(daily_returns) > 10:
            np.random.seed(42)
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            n_simulations = 1000
            n_days = 252
            simulations = np.random.normal(mean_ret, std_ret, (n_simulations, n_days))
            final_equity = np.cumsum(simulations, axis=1)
            max_loss = final_equity.min(axis=1)
            ruin_count = np.sum(max_loss < -0.4 * initial_capital)
            ruin_prob = ruin_count / n_simulations * 100
            if ruin_prob > self.thresholds["portfolio"]["ruin_probability_max"] * 100:
                alerts.append(f"Ruin probability: {ruin_prob:.2f}% (threshold: {self.thresholds['portfolio']['ruin_probability_max']*100}%)")

        weights_result = self.supabase.table("portfolio_weights").select("strategy_id", "target_weight").execute()
        if weights_result.data:
            target_weights = {w["strategy_id"]: w["target_weight"] for w in weights_result.data}
            total_pnl_portfolio = pivot.sum().sum()
            if total_pnl_portfolio != 0:
                for strategy_id in pivot.columns:
                    if strategy_id in target_weights:
                        actual_weight = pivot[strategy_id].sum() / total_pnl_portfolio * 100
                        target = target_weights[strategy_id]
                        deviation = abs(actual_weight - target) / target * 100 if target > 0 else 0
                        allocation_deviations[strategy_id] = {
                            "target": round(target, 2),
                            "actual": round(actual_weight, 2),
                            "deviation": round(deviation, 2)
                        }
                        if deviation > self.thresholds["portfolio"]["allocation_deviation_max"]:
                            alerts.append(f"Allocation deviation for strategy {strategy_id}: actual {actual_weight:.1f}% vs target {target:.1f}% (deviation {deviation:.1f}%)")

        monthly_trades = [t for t in trades_data if t.get("exit_time") and t["exit_time"] >= one_month_ago]
        total_cost = sum(t.get("cost", 0) for t in monthly_trades)
        gross_profit = sum(t.get("pnl", 0) for t in monthly_trades if t.get("pnl", 0) > 0)
        monthly_cost_pct_capital = (total_cost / initial_capital) * 100 if initial_capital > 0 else 0
        monthly_cost_pct_gross = (total_cost / gross_profit) * 100 if gross_profit > 0 else 0

        if monthly_cost_pct_capital > self.thresholds["portfolio"]["transaction_cost_max"]:
            alerts.append(f"Transaction costs: {monthly_cost_pct_capital:.2f}% of capital (threshold: {self.thresholds['portfolio']['transaction_cost_max']}%)")
        if monthly_cost_pct_gross > self.thresholds["portfolio"]["transaction_cost_gross_max"]:
            alerts.append(f"Transaction costs: {monthly_cost_pct_gross:.2f}% of gross profit (threshold: {self.thresholds['portfolio']['transaction_cost_gross_max']}%)")

        for strategy in strategies.data:
            strategy_id = strategy["strategy_id"]
            sizing = strategy.get("sizing", 1)
            instrument = strategy.get("instrument", "")
            symbol = instrument.split(" ")[0] if instrument else ""
            if symbol:
                avg_volume = regime.get_average_daily_volume(symbol)
                if avg_volume > 0:
                    position_size = sizing
                    market_impact_pct = (position_size / avg_volume) * 100
                    if market_impact_pct > self.thresholds["portfolio"]["market_impact_max"]:
                        alerts.append(f"Market impact risk for {strategy_id}: position size {position_size} is {market_impact_pct:.2f}% of daily volume (threshold: {self.thresholds['portfolio']['market_impact_max']}%)")

        try:
            def clean_json(data):
                if data is None:
                    return {}
                def default_cleaner(obj):
                    if isinstance(obj, (np.integer, np.floating)):
                        if np.isnan(obj) or np.isinf(obj):
                            return None
                        return float(obj)
                    if isinstance(obj, (pd.Timestamp, pd.NaT)):
                        return None if pd.isna(obj) else obj.isoformat()
                    if isinstance(obj, (np.ndarray, pd.Series)):
                        return obj.tolist()
                    if isinstance(obj, (dict, list)):
                        return obj
                    return str(obj)
                try:
                    return json.loads(json.dumps(data, default=default_cleaner, allow_nan=False))
                except Exception as e:
                    logger.error(f"JSON serialization error: {e}, data: {data}")
                    return {}

            exposure_json = clean_json(exposure_data)
            correlation_json = clean_json(correlation_matrix)
            concentration_json = clean_json(concentration_metrics)
            allocation_json = clean_json(allocation_deviations)

            sharpe_val = round(sharpe, 2) if sharpe and not np.isnan(sharpe) else None
            max_dd_val = round(max_dd, 2) if max_dd and not np.isnan(max_dd) else None
            current_dd_val = round(current_dd, 2) if current_dd and not np.isnan(current_dd) else None
            ruin_prob_val = round(ruin_prob, 2) if ruin_prob and not np.isnan(ruin_prob) else None

            record = {
                "date": datetime.utcnow().date().isoformat(),
                "sharpe": sharpe_val,
                "max_drawdown": max_dd_val,
                "current_drawdown": current_dd_val,
                "exposure_by_category": exposure_json,
                "correlation_matrix": correlation_json,
                "ruin_probability": ruin_prob_val,
                "transaction_cost_pct": round(monthly_cost_pct_capital, 2) if monthly_cost_pct_capital else 0.0,
                "concentration_metrics": concentration_json,
                "allocation_deviations": allocation_json,
            }
            logger.info(f"Record to insert: {record}")
            self.supabase.table("portfolio_metrics").insert(record).execute()
            logger.info("Portfolio metrics inserted successfully")
        except Exception as e:
            logger.error(f"Failed to store portfolio metrics: {e}")

        if alerts:
            subject = "[Performance Monitor] Portfolio Alerts"
            body = "Portfolio-level alerts:\n\n" + "\n".join(alerts) + f"\n\nTimestamp: {datetime.utcnow().isoformat()}"
            send_alert_email(subject, body)
            logger.warning(f"Portfolio alerts: {len(alerts)}")
        else:
            logger.info("Portfolio metrics OK")

    async def check_mt5_heartbeats(self):
        logger.info("Checking MT5 heartbeats...")

        now = datetime.utcnow()
        timeout_seconds = 120

        strategies = self.supabase.table("strategies").select("*").eq("platform", "MT5").eq("state", "Running").execute()

        for strategy in strategies.data:
            strategy_id = strategy["strategy_id"]
            last_hb = strategy.get("last_heartbeat")
            should_stop = False

            if last_hb:
                if isinstance(last_hb, str):
                    try:
                        last_hb = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                        last_hb = last_hb.replace(tzinfo=None)
                    except:
                        last_hb = None
                if last_hb:
                    elapsed = (now - last_hb).total_seconds()
                    if elapsed > timeout_seconds:
                        should_stop = True
                        logger.warning(f"Strategy {strategy_id} - heartbeat timeout: {elapsed:.0f}s")
            else:
                created_at = strategy.get("created_at")
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            created_at = created_at.replace(tzinfo=None)
                        except:
                            created_at = None
                    if created_at:
                        elapsed = (now - created_at).total_seconds()
                        if elapsed > timeout_seconds:
                            should_stop = True
                            logger.warning(f"Strategy {strategy_id} - no heartbeat ever, created {elapsed:.0f}s ago")

            if should_stop:
                self.supabase.table("strategies").update({
                    "state": "Stopped",
                    "updated_at": now.isoformat()
                }).eq("strategy_id", strategy_id).execute()
                logger.info(f"Strategy {strategy_id} marked as Stopped due to heartbeat timeout")

        logger.info("MT5 heartbeat check completed")