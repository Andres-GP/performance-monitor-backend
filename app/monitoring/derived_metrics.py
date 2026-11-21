"""Deterministic strategy and portfolio metrics from normalized monitoring records."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol

from .strategies import StrategyRegistry

UTC = timezone.utc
PAGE_SIZE = 1000


class MetricsRepository(Protocol):
    def strategy_started_at(self, strategy_id: str) -> datetime | None: ...
    def equity_samples(self, strategy_id: str) -> list[dict[str, Any]]: ...
    def trades(self, strategy_id: str) -> list[dict[str, Any]]: ...
    def upsert_daily_stats(self, record: dict[str, Any]) -> None: ...


class SupabaseMetricsRepository:
    """Paged Supabase access for the normalized monitoring tables."""

    def __init__(self, client):
        if client is None:
            raise RuntimeError("Supabase client is not configured")
        self.client = client

    def _fetch_all(self, table: str, strategy_id: str, order_column: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = (
                self.client.table(table)
                .select("*")
                .eq("strategy_id", strategy_id)
                .order(order_column)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            page = response.data or []
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    def strategy_started_at(self, strategy_id: str) -> datetime | None:
        response = (
            self.client.table("event_raw")
            .select("ts")
            .eq("strategy_id", strategy_id)
            .eq("event_type", "strategy_started")
            .not_.is_("ts", "null")
            .order("ts")
            .limit(1)
            .execute()
        )
        data = response.data or []
        return _as_utc(data[0]["ts"]) if data else None

    def equity_samples(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._fetch_all("equity_sample", strategy_id, "ts")

    def trades(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._fetch_all("trade", strategy_id, "exit_time")

    def upsert_daily_stats(self, record: dict[str, Any]) -> None:
        if record.get("strategy_id") is not None:
            conflict = "strategy_id,server_date"
        else:
            conflict = "portfolio_id,server_date"
        self.client.table("daily_stats").upsert(record, on_conflict=conflict).execute()


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def adjust_cashflows(samples: list[dict[str, Any]], *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """Remove suspected deposits/withdrawals from the performance equity curve."""
    cutoff = _as_utc(as_of) if as_of else None
    rows = sorted(
        (row for row in samples if not row.get("cashflow_ignored", False)),
        key=lambda row: _as_utc(row["ts"]),
    )
    adjusted: list[dict[str, Any]] = []
    cashflow_adjustment = 0.0
    previous_raw: float | None = None
    previous_adjusted: float | None = None
    for row in rows:
        ts = _as_utc(row["ts"])
        if cutoff and ts > cutoff:
            continue
        raw_equity = float(row["equity"])
        cashflow = bool(row.get("cashflow_suspected", False))
        if cashflow and previous_raw is not None and previous_adjusted is not None:
            cashflow_adjustment += raw_equity - previous_raw
            equity = previous_adjusted
        else:
            equity = raw_equity - cashflow_adjustment
        adjusted.append({"ts": ts, "equity": equity, "reported_equity": raw_equity})
        previous_raw = raw_equity
        previous_adjusted = equity
    return adjusted


def _equity_summary(
    curve: list[dict[str, Any]],
    *,
    offset_hours: float | None,
    offset_verified: bool,
    as_of: datetime,
) -> dict[str, Any]:
    as_of = _as_utc(as_of)
    curve = [row for row in curve if row["ts"] <= as_of]
    if not curve:
        server_date = (as_of + timedelta(hours=offset_hours)).date() if offset_verified and offset_hours is not None else None
        return {
            "equity": None,
            "performance_equity": None,
            "peak_equity": None,
            "daily_dd_pct": None,
            "total_dd_pct": None,
            "max_dd_pct": None,
            "pnl": None,
            "server_date": server_date,
            "_day_start_equity": None,
        }

    performance_equity = float(curve[-1]["equity"])
    equity = float(curve[-1].get("reported_equity", performance_equity))
    peak_equity = max(float(row["equity"]) for row in curve)
    running_peak = float(curve[0]["equity"])
    max_dd_pct = 0.0
    for row in curve:
        value = float(row["equity"])
        running_peak = max(running_peak, value)
        if running_peak > 0:
            max_dd_pct = max(max_dd_pct, max(0.0, (running_peak - value) / running_peak * 100))
    total_dd_pct = max(0.0, (peak_equity - performance_equity) / peak_equity * 100) if peak_equity > 0 else None

    if not offset_verified or offset_hours is None:
        return {
            "equity": equity,
            "performance_equity": performance_equity,
            "peak_equity": peak_equity,
            "daily_dd_pct": None,
            "total_dd_pct": total_dd_pct,
            "max_dd_pct": max_dd_pct,
            "pnl": None,
            "server_date": None,
            "_day_start_equity": None,
        }

    offset = timedelta(hours=offset_hours)
    server_date = (as_of + offset).date()
    server_midnight_utc = datetime.combine(server_date, time.min, tzinfo=UTC) - offset
    before_day = [row for row in curve if row["ts"] <= server_midnight_utc]
    within_day = [row for row in curve if row["ts"] > server_midnight_utc]
    if before_day:
        day_start_equity = float(before_day[-1]["equity"])
    elif within_day:
        day_start_equity = float(within_day[0]["equity"])
    else:
        day_start_equity = float(curve[0]["equity"])
    daily_dd_pct = (
        max(0.0, (day_start_equity - performance_equity) / day_start_equity * 100)
        if day_start_equity > 0
        else None
    )
    return {
        "equity": equity,
        "peak_equity": peak_equity,
        "daily_dd_pct": daily_dd_pct,
        "total_dd_pct": total_dd_pct,
        "max_dd_pct": max_dd_pct,
        "pnl": performance_equity - day_start_equity,
        "performance_equity": performance_equity,
        "server_date": server_date,
        "_day_start_equity": day_start_equity,
    }


def _sorted_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (trade for trade in trades if not trade.get("cashflow_suspected", False)),
        key=lambda trade: _as_utc(trade["exit_time"]),
    )


def calculate_trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = _sorted_trades(trades)
    profits = [float(trade["profit"]) for trade in ordered]
    wins = sum(profit > 0 for profit in profits)
    gross_profit = sum(profit for profit in profits if profit > 0)
    gross_loss = -sum(profit for profit in profits if profit < 0)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    average_net_per_trade = sum(profits) / len(profits) if profits else None
    if len(profits) >= 2:
        mean_profit = average_net_per_trade
        variance = sum((profit - mean_profit) ** 2 for profit in profits) / (len(profits) - 1)
        standard_error = (variance / len(profits)) ** 0.5
        t_stat_net_per_trade = mean_profit / standard_error if standard_error > 0 else None
    else:
        t_stat_net_per_trade = None
    holds = [float(trade["hold_minutes"]) for trade in ordered if trade.get("hold_minutes") is not None]
    expectancy_values = [
        float(trade["pnl_pct_equity"])
        for trade in ordered
        if trade.get("pnl_pct_equity") is not None
    ]
    current_loss_streak = 0
    max_loss_streak = 0
    for profit in profits:
        if profit < 0:
            current_loss_streak += 1
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0
    return {
        "trade_count": len(ordered),
        "net_profit": sum(profits) if profits else None,
        "average_net_per_trade": average_net_per_trade,
        "t_stat_net_per_trade": t_stat_net_per_trade,
        "win_rate": wins / len(ordered) * 100 if ordered else None,
        "profit_factor": profit_factor,
        "expectancy_pct": sum(expectancy_values) / len(expectancy_values) if expectancy_values else None,
        "avg_hold_minutes": sum(holds) / len(holds) if holds else None,
        "current_loss_streak": current_loss_streak if profits else None,
        "max_loss_streak": max_loss_streak if profits else None,
    }


def _rolling_metrics(trades: list[dict[str, Any]], window: int) -> dict[str, Any]:
    selected = _sorted_trades(trades)[-window:]
    return {"n_trades": len(selected), **calculate_trade_metrics(selected)}


def calculate_strategy_metrics(
    strategy_id: str,
    samples: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    offset_hours: float | None,
    offset_verified: bool,
    as_of: datetime,
) -> dict[str, Any]:
    curve = adjust_cashflows(samples, as_of=as_of)
    equity = _equity_summary(
        curve,
        offset_hours=offset_hours,
        offset_verified=offset_verified,
        as_of=as_of,
    )
    metrics = calculate_trade_metrics(trades)
    recent_cutoff = _as_utc(as_of) - timedelta(days=90)
    recent_trade_count = sum(_as_utc(trade["exit_time"]) >= recent_cutoff for trade in _sorted_trades(trades))
    return {
        "strategy_id": strategy_id,
        "portfolio_id": None,
        "ts": _as_utc(as_of),
        **equity,
        **metrics,
        "trades_per_year_live_90d": recent_trade_count / 90 * 365,
        "rolling_20": _rolling_metrics(trades, 20),
        "rolling_50": _rolling_metrics(trades, 50),
        "_trades": _sorted_trades(trades),
        "_equity_curve": curve,
    }


def merge_account_equity_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one freshest account-equity sample per minute across EAs."""
    by_minute: dict[datetime, dict[str, Any]] = {}
    for sample in samples:
        ts = _as_utc(sample["ts"])
        minute = ts.replace(second=0, microsecond=0)
        current = by_minute.get(minute)
        if current is None or ts >= current["ts"]:
            by_minute[minute] = {**sample, "ts": ts}
    return [by_minute[key] for key in sorted(by_minute)]


def _merge_account_equity_curves(curves: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Combine shared-account EA streams without counting account equity twice."""
    return merge_account_equity_samples([sample for curve in curves for sample in curve])


def calculate_portfolio_metrics(
    portfolio_id: str,
    strategy_metrics: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    offset_hours: float | None,
    offset_verified: bool,
    as_of: datetime,
) -> dict[str, Any]:
    curve = _merge_account_equity_curves([item["_equity_curve"] for item in strategy_metrics])
    equity = _equity_summary(
        curve,
        offset_hours=offset_hours,
        offset_verified=offset_verified,
        as_of=as_of,
    )
    metrics = calculate_trade_metrics(trades)
    return {
        "strategy_id": None,
        "portfolio_id": portfolio_id,
        "ts": _as_utc(as_of),
        **equity,
        **metrics,
        "rolling_20": _rolling_metrics(trades, 20),
        "rolling_50": _rolling_metrics(trades, 50),
        "_equity_curve": curve,
    }


def _daily_stats_record(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, (datetime, date)) else value
        for key, value in metrics.items()
        if not key.startswith("_")
    }


def recalculate_monitoring_metrics(
    repository: MetricsRepository,
    registry: StrategyRegistry,
    *,
    as_of: datetime | None = None,
    portfolio_id: str | None = None,
) -> dict[str, Any]:
    """Recompute all current strategy and account metrics, upserting daily snapshots."""
    as_of = _as_utc(as_of or datetime.now(UTC))
    strategies_by_portfolio: dict[str, list[dict[str, Any]]] = {}
    trades_by_portfolio: dict[str, list[dict[str, Any]]] = {}
    strategy_results: dict[str, dict[str, Any]] = {}

    for strategy in registry.strategies:
        if portfolio_id and strategy.portfolio_id != portfolio_id:
            continue
        portfolio = next(item for item in registry.portfolios if item.id == strategy.portfolio_id)
        started_at = repository.strategy_started_at(strategy.id)
        samples = repository.equity_samples(strategy.id)
        trades = repository.trades(strategy.id)
        if started_at:
            started_at = _as_utc(started_at)
            samples = [row for row in samples if _as_utc(row["ts"]) >= started_at]
            trades = [row for row in trades if _as_utc(row["exit_time"]) >= started_at]
        metrics = calculate_strategy_metrics(
            strategy.id,
            samples,
            trades,
            offset_hours=portfolio.server_utc_offset_hours,
            offset_verified=portfolio.server_time_to_utc_enabled,
            as_of=as_of,
        )
        metrics["trades_per_year_expected"] = (
            strategy.baselines.bt_trades_per_month * 12
            if strategy.baselines.bt_trades_per_month is not None else None
        )
        expected_frequency = metrics["trades_per_year_expected"]
        metrics["frequency_vs_expected_pct"] = (
            (metrics["trades_per_year_live_90d"] - expected_frequency) / expected_frequency * 100
            if expected_frequency and expected_frequency > 0 else None
        )
        strategy_results[strategy.id] = metrics
        strategies_by_portfolio.setdefault(strategy.portfolio_id, []).append(metrics)
        trades_by_portfolio.setdefault(strategy.portfolio_id, []).extend(trades)
        if metrics["server_date"] is not None:
            repository.upsert_daily_stats(_daily_stats_record(metrics))

    portfolio_results: dict[str, dict[str, Any]] = {}
    for portfolio in registry.portfolios:
        if portfolio_id and portfolio.id != portfolio_id:
            continue
        members = strategies_by_portfolio.get(portfolio.id, [])
        metrics = calculate_portfolio_metrics(
            portfolio.id,
            members,
            trades_by_portfolio.get(portfolio.id, []),
            offset_hours=portfolio.server_utc_offset_hours,
            offset_verified=portfolio.server_time_to_utc_enabled,
            as_of=as_of,
        )
        portfolio_results[portfolio.id] = metrics
        if metrics["server_date"] is not None:
            repository.upsert_daily_stats(_daily_stats_record(metrics))

    return {"strategies": strategy_results, "portfolios": portfolio_results}


def run_metrics_job(
    client,
    registry: StrategyRegistry,
    *,
    as_of: datetime | None = None,
    portfolio_id: str | None = None,
) -> dict[str, Any]:
    return recalculate_monitoring_metrics(
        SupabaseMetricsRepository(client),
        registry,
        as_of=as_of,
        portfolio_id=portfolio_id,
    )


def server_daily_close_utc(offset_hours: float) -> tuple[int, int]:
    """Return the UTC hour/minute corresponding to 23:59 broker-server time."""
    server_zone = timezone(timedelta(hours=offset_hours))
    local_close = datetime(2020, 1, 1, 23, 59, tzinfo=server_zone)
    utc_close = local_close.astimezone(UTC)
    return utc_close.hour, utc_close.minute
