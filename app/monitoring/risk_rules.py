"""Risk threshold checks (Step 6) over the derived equity metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ingestion import SupabaseMonitoringRepository
from .strategies import Portfolio, Strategy, StrategyRegistry

UTC = timezone.utc
_LEVELS = ((50, "medium"), (70, "high"), (90, "critical"))


def _drawdown_signals(metric: dict[str, Any], daily_limit: float, total_limit: float):
    signals = []
    for dd_name, limit, value in (
        ("DAILY", daily_limit, metric.get("daily_dd_pct")),
        ("TOTAL", total_limit, metric.get("total_dd_pct")),
    ):
        # Daily DD is unavailable until the broker-server offset is verified.
        if value is None or limit is None or limit <= 0:
            continue
        ratio_pct = float(value) / float(limit) * 100
        for threshold, severity in _LEVELS:
            if ratio_pct >= threshold:
                signals.append({
                    "rule_key": f"DD_{dd_name}_{threshold}",
                    "severity": severity,
                    "context": {
                        "drawdown_pct": float(value),
                        "limit_pct": float(limit),
                        "limit_used_pct": ratio_pct,
                        "threshold_pct": threshold,
                    },
                })
    return signals


def evaluate_strategy_risk_rules(
    strategy: Strategy,
    metric: dict[str, Any],
    *,
    last_kill_at: datetime | None = None,
    last_started_at: datetime | None = None,
) -> list[dict[str, Any]]:
    signals = _drawdown_signals(
        metric,
        strategy.strategy_dd_daily_limit_pct,
        strategy.strategy_dd_total_limit_pct,
    )
    if last_kill_at and (last_started_at is None or last_kill_at >= last_started_at):
        signals.append({
            "rule_key": "KILL_ACTIVE",
            "severity": "critical",
            "context": {"kill_switch_at": last_kill_at.isoformat()},
        })
    if strategy.known_risk:
        signals.append({
            "rule_key": strategy.known_risk.key,
            "severity": "info",
            "context": {"message": strategy.known_risk.message},
        })
    return signals


def evaluate_portfolio_risk_rules(
    portfolio: Portfolio,
    metric: dict[str, Any],
    *,
    daily_limit: float | None = None,
    total_limit: float | None = None,
) -> list[dict[str, Any]]:
    daily_limit = portfolio.daily_dd_limit_pct if daily_limit is None else daily_limit
    total_limit = portfolio.total_dd_limit_pct if total_limit is None else total_limit
    signals = _drawdown_signals(metric, daily_limit, total_limit)
    for signal in signals:
        signal["rule_key"] = "PORTFOLIO_" + signal["rule_key"]
    hard_limit = portfolio.broker_hard_limit_pct
    total_dd = metric.get("total_dd_pct")
    if hard_limit is not None and total_dd is not None and float(total_dd) >= 0.9 * hard_limit:
        signals.append({
            "rule_key": "BROKER_HARD_LIMIT",
            "severity": "critical",
            "context": {
                "total_dd_pct": float(total_dd),
                "broker_hard_limit_pct": hard_limit,
                "threshold_pct": hard_limit * 0.9,
            },
        })
    return signals


def _latest_event(client, strategy_id: str, event_type: str, payload_key: str, payload_value: str):
    rows = (
        client.table("event_raw")
        .select("received_at")
        .eq("strategy_id", strategy_id)
        .eq("event_type", event_type)
        .filter(f"payload->>{payload_key}", "eq", payload_value)
        .order("received_at", desc=True)
        .limit(1)
        .execute()
        .data or []
    )
    return rows[0].get("received_at") if rows else None


def run_risk_rules(client, registry: StrategyRegistry, metrics: dict[str, Any], *, now=None):
    """Persist strategy and portfolio risk signals from one derived-metrics pass."""
    now = now or datetime.now(UTC)
    alerts = []
    repository = SupabaseMonitoringRepository(client)
    for strategy in registry.strategies:
        metric = metrics.get("strategies", {}).get(strategy.id, {})
        kill_at = _latest_event(client, strategy.id, "health_alert", "type", "KillSwitch")
        if kill_at is None:
            kill_at = _latest_event(client, strategy.id, "health_alert", "problem_type", "KillSwitch")
        started_rows = (
            client.table("event_raw").select("received_at").eq("strategy_id", strategy.id)
            .eq("event_type", "strategy_started").order("received_at", desc=True).limit(1).execute().data or []
        )
        if started_rows:
            started_at = started_rows[0].get("received_at")
        else:
            started_at = None
        strategy_signals = evaluate_strategy_risk_rules(
            strategy,
            metric,
            last_kill_at=_datetime(kill_at),
            last_started_at=_datetime(started_at),
        )
        for signal in strategy_signals:
            alerts.append(_persist(repository, signal, now, strategy_id=strategy.id))

    for portfolio in registry.portfolios:
        metric = metrics.get("portfolios", {}).get(portfolio.id, {})
        signals = evaluate_portfolio_risk_rules(
            portfolio,
            metric,
            daily_limit=registry.effective_portfolio_limit(portfolio.id, "daily"),
            total_limit=registry.effective_portfolio_limit(portfolio.id, "total"),
        )
        for signal in signals:
            alerts.append(_persist(repository, signal, now, portfolio_id=portfolio.id))
    return alerts


def _datetime(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _persist(repository, signal, now, *, strategy_id=None, portfolio_id=None):
    record = {
        **signal,
        "strategy_id": strategy_id,
        "portfolio_id": portfolio_id,
        "status": "open",
        "first_seen": now.isoformat(),
        "last_seen": now.isoformat(),
        "count": 1,
    }
    repository.insert_alert(record)
    return record
