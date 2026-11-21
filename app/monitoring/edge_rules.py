"""Backtest-relative edge decay checks (Step 8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .ingestion import SupabaseMonitoringRepository
from .strategies import Strategy, StrategyRegistry

UTC = timezone.utc


def _fraction(value: float) -> float:
    value = float(value)
    return value / 100 if value > 1 else value


def evaluate_edge_decay(
    strategy: Strategy,
    metrics: dict[str, Any],
    trades: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Return status and backtest-relative signals for one strategy."""
    if now.tzinfo is None:
        raise ValueError("edge evaluation requires an aware timestamp")
    now = now.astimezone(UTC)
    window = 20 if strategy.id == "RSI2_QQQ" else 50
    rolling = metrics.get("rolling_20" if window == 20 else "rolling_50", {})
    n_trades = int(rolling.get("n_trades", rolling.get("trade_count", 0)))
    applicable_baselines = strategy.baselines.model_dump(exclude_none=True)
    if n_trades < 20:
        return {"state": "INSUFFICIENT_DATA", "n_trades": n_trades, "signals": []}
    if not applicable_baselines:
        return {"state": "NO_BASELINE", "n_trades": n_trades, "signals": []}

    signals: list[dict[str, Any]] = []

    def add(rule_key: str, severity: str, context: dict[str, Any]):
        signals.append({"rule_key": rule_key, "severity": severity, "context": {**context, "n_trades": n_trades}})

    bt_wr = strategy.baselines.bt_win_rate
    live_wr = rolling.get("win_rate")
    if bt_wr is not None and live_wr is not None:
        p = min(1.0, max(0.0, _fraction(bt_wr)))
        observed = min(1.0, max(0.0, float(live_wr) / 100))
        band = 2 * (p * (1 - p) / n_trades) ** 0.5
        if abs(observed - p) > band:
            add("WR_DRIFT", "medium", {
                "live_win_rate": observed,
                "backtest_win_rate": p,
                "two_sigma_band": band,
            })

    bt_pf = strategy.baselines.bt_profit_factor
    live_pf = rolling.get("profit_factor")
    if bt_pf is not None and live_pf is not None and (float(live_pf) < 1.0 or float(live_pf) < 0.5 * bt_pf):
        add("PF_DRIFT", "high", {"live_profit_factor": live_pf, "backtest_profit_factor": bt_pf, "threshold": max(1.0, 0.5 * bt_pf)})

    live_expectancy = rolling.get("expectancy_pct")
    if live_expectancy is not None and float(live_expectancy) < 0:
        add("EXPECTANCY_NEG", "high", {"live_expectancy_pct": live_expectancy, "threshold_pct": 0})

    baseline_frequency = strategy.baselines.bt_trades_per_month
    if baseline_frequency is not None:
        cutoff = now - timedelta(days=90)
        recent_count = sum(_dt(trade["exit_time"]) >= cutoff for trade in trades if trade.get("exit_time"))
        live_frequency = recent_count / 3
        if live_frequency < 0.5 * baseline_frequency or live_frequency > 1.5 * baseline_frequency:
            add("FREQ_DRIFT", "medium", {
                "live_trades_per_month": live_frequency,
                "backtest_trades_per_month": baseline_frequency,
                "window_days": 90,
            })

    baseline_cost = strategy.baselines.bt_cost_ratio
    cost_rows = [
        trade for trade in trades[-window:]
        if any(trade.get(field) is not None for field in ("swap", "swap_estimate", "commission", "spread_cost"))
    ]
    if baseline_cost is not None and cost_rows:
        # MT5's normalized `profit` is already net of broker costs. Add known
        # costs back to estimate gross positive P&L; never require the legacy
        # `swap_estimate` field, which the EA contract does not send.
        gross_wins = [
            float(row["profit"])
            + abs(float(row.get("commission") or 0))
            + abs(float(row.get("swap", row.get("swap_estimate")) or 0))
            + abs(float(row.get("spread_cost") or 0))
            for row in cost_rows
        ]
        positive_gross = [value for value in gross_wins if value > 0]
        if positive_gross:
            average_gross = sum(positive_gross) / len(positive_gross)
            average_cost = sum(
                abs(float(row.get("commission") or 0))
                + abs(float(row.get("swap", row.get("swap_estimate")) or 0))
                + abs(float(row.get("spread_cost") or 0))
                for row in cost_rows
            ) / len(cost_rows)
            live_cost_ratio = average_cost / average_gross
            if live_cost_ratio > 2 * baseline_cost:
                add("COST_DRIFT", "medium", {
                    "live_cost_ratio": live_cost_ratio,
                    "backtest_cost_ratio": baseline_cost,
                    "threshold": 2 * baseline_cost,
                })

    baseline_streak = strategy.baselines.bt_max_loss_streak
    current_streak = rolling.get("current_loss_streak")
    if baseline_streak is not None and current_streak is not None and int(current_streak) > baseline_streak:
        add("LOSS_STREAK", "high", {
            "current_loss_streak": current_streak,
            "backtest_max_loss_streak": baseline_streak,
        })

    return {"state": "ACTIVE", "n_trades": n_trades, "signals": signals}


def run_edge_rules(client, registry: StrategyRegistry, metrics: dict[str, Any], *, now=None):
    now = now or datetime.now(UTC)
    repository = SupabaseMonitoringRepository(client)
    states: dict[str, dict[str, Any]] = {}
    alerts = []
    for strategy in registry.strategies:
        derived = metrics.get("strategies", {}).get(strategy.id, {})
        evaluation = evaluate_edge_decay(
            strategy,
            derived,
            derived.get("_trades", []),
            now=now,
        )
        states[strategy.id] = {"state": evaluation["state"], "n_trades": evaluation["n_trades"]}
        for signal in evaluation["signals"]:
            record = {
                **signal,
                "strategy_id": strategy.id,
                "portfolio_id": None,
                "status": "open",
                "first_seen": now.isoformat(),
                "last_seen": now.isoformat(),
                "count": 1,
            }
            repository.insert_alert(record)
            alerts.append(record)
    return {"states": states, "alerts": alerts}


def _dt(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
