from datetime import datetime, timezone

import pytest

from app.monitoring.derived_metrics import (
    calculate_portfolio_metrics,
    calculate_strategy_metrics,
    calculate_trade_metrics,
    recalculate_monitoring_metrics,
    server_daily_close_utc,
)
from app.monitoring.strategies import load_registry


class MemoryMetricsRepository:
    def __init__(self):
        self.equities = {}
        self.trade_rows = {}
        self.started = {}
        self.daily_stats = []

    def strategy_started_at(self, strategy_id):
        return self.started.get(strategy_id)

    def equity_samples(self, strategy_id):
        return list(self.equities.get(strategy_id, []))

    def trades(self, strategy_id):
        return list(self.trade_rows.get(strategy_id, []))

    def upsert_daily_stats(self, record):
        self.daily_stats.append(dict(record))


def registry_with_offsets():
    registry = load_registry()
    portfolios = [
        item.model_copy(update={"server_utc_offset_hours": 2.0, "server_utc_offset_verified": True})
        for item in registry.portfolios
    ]
    return registry.model_copy(update={"portfolios": portfolios})


def test_trade_metrics_match_hand_calculated_series():
    trades = [
        {"profit": 100, "pnl_pct_equity": 10, "hold_minutes": 60, "exit_time": "2026-01-01T00:01:00Z"},
        {"profit": -50, "pnl_pct_equity": -5, "hold_minutes": 120, "exit_time": "2026-01-02T00:01:00Z"},
        {"profit": -25, "pnl_pct_equity": -2.5, "hold_minutes": 90, "exit_time": "2026-01-03T00:01:00Z"},
        {"profit": 75, "pnl_pct_equity": 7.5, "hold_minutes": 30, "exit_time": "2026-01-04T00:01:00Z"},
        {"profit": 0, "pnl_pct_equity": 0, "hold_minutes": 45, "exit_time": "2026-01-05T00:01:00Z"},
    ]
    metrics = calculate_trade_metrics(trades)
    assert metrics == {
        "trade_count": 5,
        "win_rate": 40.0,
        "profit_factor": pytest.approx(175 / 75),
        "expectancy_pct": 2.0,
        "avg_hold_minutes": 69.0,
        "current_loss_streak": 0,
        "max_loss_streak": 2,
    }
    strategy = calculate_strategy_metrics(
        "S", [], trades, offset_hours=None, offset_verified=False,
        as_of=datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    assert strategy["rolling_20"]["n_trades"] == 5
    assert strategy["rolling_50"]["profit_factor"] == pytest.approx(175 / 75)


def test_strategy_drawdown_and_pnl_ignore_suspected_cashflow():
    samples = [
        {"ts": "2026-01-02T00:00:00Z", "equity": 1000, "cashflow_suspected": False},
        {"ts": "2026-01-02T01:00:00Z", "equity": 1200, "cashflow_suspected": True},
        {"ts": "2026-01-02T02:00:00Z", "equity": 1180, "cashflow_suspected": False},
    ]
    metrics = calculate_strategy_metrics(
        "S", samples, [], offset_hours=0, offset_verified=True,
        as_of=datetime(2026, 1, 2, 3, tzinfo=timezone.utc),
    )
    assert metrics["equity"] == 1180
    assert metrics["performance_equity"] == 980
    assert metrics["peak_equity"] == 1000
    assert metrics["daily_dd_pct"] == pytest.approx(2.0)
    assert metrics["total_dd_pct"] == pytest.approx(2.0)
    assert metrics["max_dd_pct"] == pytest.approx(2.0)
    assert metrics["pnl"] == -20


def test_daily_drawdown_uses_server_calendar_date_across_utc_midnight():
    samples = [
        {"ts": "2026-01-01T21:50:00Z", "equity": 100},
        {"ts": "2026-01-01T22:10:00Z", "equity": 90},
    ]
    metrics = calculate_strategy_metrics(
        "S", samples, [], offset_hours=2, offset_verified=True,
        as_of=datetime(2026, 1, 1, 22, 15, tzinfo=timezone.utc),
    )
    assert metrics["server_date"].isoformat() == "2026-01-02"
    assert metrics["daily_dd_pct"] == pytest.approx(10)


def test_daily_dd_is_disabled_until_server_offset_is_verified():
    metrics = calculate_strategy_metrics(
        "S", [{"ts": "2026-01-02T00:00:00Z", "equity": 100}], [],
        offset_hours=None, offset_verified=False,
        as_of=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
    )
    assert metrics["equity"] == 100
    assert metrics["total_dd_pct"] == 0
    assert metrics["daily_dd_pct"] is None
    assert metrics["server_date"] is None


def test_portfolio_uses_freshest_account_equity_instead_of_summing_ea_reports():
    as_of = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    strategy_metrics = [
        calculate_strategy_metrics(
            "A", [{"ts": "2026-01-01T00:00:00Z", "equity": 100}, {"ts": "2026-01-01T00:01:00Z", "equity": 110}], [],
            offset_hours=0, offset_verified=True, as_of=as_of,
        ),
        calculate_strategy_metrics(
            "B", [{"ts": "2026-01-01T00:00:30Z", "equity": 100}, {"ts": "2026-01-01T00:01:30Z", "equity": 112}], [],
            offset_hours=0, offset_verified=True, as_of=as_of,
        ),
    ]
    metrics = calculate_portfolio_metrics(
        "P", strategy_metrics, [], offset_hours=0, offset_verified=True, as_of=as_of
    )
    assert metrics["equity"] == 112
    assert metrics["peak_equity"] == 112


def test_recalculation_persists_daily_rows_only_for_verified_offsets():
    repository = MemoryMetricsRepository()
    registry = load_registry()
    as_of = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    result = recalculate_monitoring_metrics(repository, registry, as_of=as_of)
    assert len(result["strategies"]) == 5
    assert len(result["portfolios"]) == 2
    assert repository.daily_stats == []

    verified_registry = registry_with_offsets()
    result = recalculate_monitoring_metrics(repository, verified_registry, as_of=as_of)
    assert len(repository.daily_stats) == 7
    assert all(record["server_date"] == "2026-11-19" for record in repository.daily_stats)
    assert result["portfolios"]["P_AXI"]["trade_count"] == 0


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(2, (21, 59)), (-5, (4, 59)), (5.5, (18, 29))],
)
def test_daily_close_is_scheduled_at_utc_equivalent_of_server_2359(offset, expected):
    assert server_daily_close_utc(offset) == expected
