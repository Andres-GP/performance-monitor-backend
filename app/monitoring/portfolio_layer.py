"""Portfolio aggregates, rolling strategy correlations, and pair checks (Step 9)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .ingestion import SupabaseMonitoringRepository
from .strategies import StrategyRegistry

UTC = timezone.utc
CORRELATION_DAYS = 60
MIN_CORRELATION_OBSERVATIONS = 20


def _dt(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < MIN_CORRELATION_OBSERVATIONS:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mean_x for x in xs], [y - mean_y for y in ys]
    denominator = (sum(value * value for value in dx) * sum(value * value for value in dy)) ** 0.5
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / denominator


def _daily_pnl(trades: list[dict[str, Any]]) -> dict[date, float]:
    result: dict[date, float] = {}
    use_equity_returns = bool(trades) and all(trade.get("pnl_pct_equity") is not None for trade in trades)
    for trade in trades:
        if trade.get("cashflow_suspected"):
            continue
        day = _dt(trade["exit_time"]).date()
        value = trade.get("pnl_pct_equity") if use_equity_returns else trade.get("profit")
        result[day] = result.get(day, 0.0) + float(value or 0)
    return result


def _edge_family_pair(left, right) -> bool:
    return bool(left.edge_family and left.edge_family == right.edge_family)


def _correlation_matrix(registry, strategy_metrics, now, prior_high_counts=None):
    prior_high_counts = prior_high_counts or {}
    today = now.date()
    first_day = today - timedelta(days=CORRELATION_DAYS - 1)
    strategies = registry.strategies
    series = {item.id: _daily_pnl(strategy_metrics.get(item.id, {}).get("_trades", [])) for item in strategies}
    first_observed = {
        sid: min((day for day in values if day >= first_day), default=None)
        for sid, values in series.items()
    }
    pairs = []
    alerts = []
    high_counts = {}
    for index, left in enumerate(strategies):
        for right in strategies[index + 1:]:
            pair_key = "|".join(sorted((left.id, right.id)))
            same_edge = _edge_family_pair(left, right)
            left_first, right_first = first_observed[left.id], first_observed[right.id]
            start = max(left_first, right_first) if left_first and right_first else None
            days = [start + timedelta(days=offset) for offset in range((today - start).days + 1)] if start else []
            days = [day for day in days if day >= first_day]
            x = [series[left.id].get(day, 0.0) for day in days]
            y = [series[right.id].get(day, 0.0) for day in days]
            correlation = _pearson(x, y)
            band = "insufficient_data" if correlation is None else (
                "red" if correlation > 0.5 else "attention" if correlation >= 0.2 else "green"
            )
            current_high_count = 0
            if correlation is not None and correlation > 0.5 and not same_edge:
                current_high_count = prior_high_counts.get(pair_key, 0) + 1
                if current_high_count >= 2:
                    alerts.append({
                        "rule_key": "CORR_HIGH",
                        "severity": "medium",
                        "strategy_id": left.id,
                        "context": {
                            "pair": [left.id, right.id],
                            "correlation": correlation,
                            "observations": len(days),
                            "window_days": CORRELATION_DAYS,
                        },
                    })
            high_counts[pair_key] = current_high_count
            pairs.append({
                "strategy_a": left.id,
                "strategy_b": right.id,
                "correlation": correlation,
                "observations": len(days),
                "band": band,
                "same_edge": same_edge,
            })
    return pairs, alerts, high_counts


def _gotobi_dates(strategy, start: date, end: date) -> list[date]:
    dates = []
    day = start
    values = strategy.entry.gotobi_dates or [5, 10, 15, 20, 25, 30, "end_of_month"]
    excluded = set(strategy.entry.excluded_dates or [])
    while day <= end:
        eom = day.day == calendar.monthrange(day.year, day.month)[1]
        if (day.day in [value for value in values if isinstance(value, int)] or ("end_of_month" in values and eom)) and day.isoformat() not in excluded:
            dates.append(day)
        day += timedelta(days=1)
    return dates


def _gotobi_divergence(registry, strategy_metrics, now):
    axi = next((item for item in registry.strategies if item.id == "GOTOBI_USDJPY_AXI"), None)
    dwx = next((item for item in registry.strategies if item.id == "GOTOBI_USDJPY_DWX"), None)
    if axi is None or dwx is None:
        return None
    start = now.date() - timedelta(days=60)
    axi_daily = _daily_pnl(strategy_metrics.get(axi.id, {}).get("_trades", []))
    dwx_daily = _daily_pnl(strategy_metrics.get(dwx.id, {}).get("_trades", []))
    shared_days = [day for day in _gotobi_dates(axi, start, now.date()) if day in axi_daily and day in dwx_daily]
    opposite = [day for day in shared_days if axi_daily[day] * dwx_daily[day] < 0]
    if len(opposite) < 3 or opposite[-3:] != shared_days[-3:]:
        return None
    return {
        "rule_key": "DIVERGENCE_GOTOBI",
        "severity": "medium",
        "strategy_id": axi.id,
        "context": {
            "pair": [axi.id, dwx.id],
            "opposite_sign_days": [day.isoformat() for day in opposite[-3:]],
            "axi_pnl": [axi_daily[day] for day in opposite[-3:]],
            "dwx_pnl": [dwx_daily[day] for day in opposite[-3:]],
        },
    }


def calculate_portfolio_layer(registry, metrics, *, now=None, prior_high_counts=None):
    """Build portfolio-level period PnL, contributions, equity curves and correlations."""
    now = _dt(now or datetime.now(UTC))
    strategy_metrics = metrics.get("strategies", {})
    portfolio_metrics = metrics.get("portfolios", {})
    result = {}
    for portfolio in registry.portfolios:
        members = [item for item in registry.strategies if item.portfolio_id == portfolio.id]
        contributions = {}
        total_periods = {"daily": 0.0, "weekly": 0.0, "monthly": 0.0}
        for strategy in members:
            trades = strategy_metrics.get(strategy.id, {}).get("_trades", [])
            contributions[strategy.id] = sum(float(row.get("profit") or 0) for row in trades if _dt(row["exit_time"]) >= now - timedelta(days=30))
            for row in trades:
                exit_at = _dt(row["exit_time"])
                value = float(row.get("profit") or 0)
                if exit_at.date() == now.date():
                    total_periods["daily"] += value
                if exit_at >= now - timedelta(days=7):
                    total_periods["weekly"] += value
                if exit_at.year == now.year and exit_at.month == now.month:
                    total_periods["monthly"] += value
        base = portfolio_metrics.get(portfolio.id, {})
        curve = base.get("_equity_curve", [])
        result[portfolio.id] = {
            "equity": base.get("equity"),
            "daily_dd_pct": base.get("daily_dd_pct"),
            "total_dd_pct": base.get("total_dd_pct"),
            "pnl_daily_realized": total_periods["daily"],
            "pnl_weekly_realized": total_periods["weekly"],
            "pnl_monthly_realized": total_periods["monthly"],
            "strategy_contribution_30d": contributions,
            "open_positions": None,
            "gross_notional_over_equity": None,
            "equity_curve": [
                {"ts": _dt(row["ts"]).isoformat(), "equity": row.get("reported_equity", row["equity"])}
                for row in curve
            ],
            "period_basis": "UTC trade exit dates; broker server offsets are unverified",
        }

    pairs, corr_alerts, high_counts = _correlation_matrix(registry, strategy_metrics, now, prior_high_counts)
    divergence = _gotobi_divergence(registry, strategy_metrics, now)
    alerts = corr_alerts + ([divergence] if divergence else [])
    return {
        "portfolios": result,
        "correlations": pairs,
        "alerts": alerts,
        "high_counts": high_counts,
    }


def run_portfolio_layer(client, registry, metrics, *, now=None):
    now = _dt(now or datetime.now(UTC))
    previous = {}
    pair_keys = [
        "|".join(sorted((left.id, right.id)))
        for index, left in enumerate(registry.strategies)
        for right in registry.strategies[index + 1:]
    ]
    for pair_key in pair_keys:
        rows = (
            client.table("rule_state").select("state")
            .eq("rule_key", "CORR_HIGH").eq("scope_type", "strategy").eq("scope_id", pair_key)
            .limit(1).execute().data or []
        )
        if rows:
            previous[pair_key] = int((rows[0].get("state") or {}).get("consecutive_high", 0))
    result = calculate_portfolio_layer(registry, metrics, now=now, prior_high_counts=previous)
    for pair_key, count in result["high_counts"].items():
        client.table("rule_state").upsert({
            "rule_key": "CORR_HIGH",
            "scope_type": "strategy",
            "scope_id": pair_key,
            "last_evaluated_at": now.isoformat(),
            "consecutive_failures": count,
            "consecutive_passes": 0 if count else 1,
            "state": {"consecutive_high": count},
        }, on_conflict="rule_key,scope_type,scope_id").execute()
    for portfolio_id, aggregate in result["portfolios"].items():
        server_date = (metrics.get("portfolios", {}).get(portfolio_id) or {}).get("server_date")
        if server_date is None:
            continue
        client.table("daily_stats").update({
            "pnl_daily_realized": aggregate["pnl_daily_realized"],
            "pnl_weekly_realized": aggregate["pnl_weekly_realized"],
            "pnl_monthly_realized": aggregate["pnl_monthly_realized"],
            "open_positions_count": aggregate["open_positions"],
            "gross_notional_over_equity": aggregate["gross_notional_over_equity"],
            "strategy_contribution_30d": aggregate["strategy_contribution_30d"],
            "correlation_matrix": result["correlations"],
        }).eq("portfolio_id", portfolio_id).eq("server_date", str(server_date)).execute()
    repository = SupabaseMonitoringRepository(client)
    for signal in result["alerts"]:
        record = {
            **signal,
            "portfolio_id": None,
            "status": "open",
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "count": 1,
        }
        repository.insert_alert(record)
    return result
