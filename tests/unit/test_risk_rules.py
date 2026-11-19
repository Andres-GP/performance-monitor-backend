from datetime import datetime, timezone

from app.monitoring.risk_rules import (
    evaluate_portfolio_risk_rules,
    evaluate_strategy_risk_rules,
)
from app.monitoring.strategies import load_registry


UTC = timezone.utc
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


def pick(items, item_id):
    return next(item for item in items if item.id == item_id)


def test_strategy_drawdown_levels_use_strategy_limits_and_skip_unknown_daily_dd():
    registry = load_registry()
    target = pick(registry.strategies, "GOTOBI_USDJPY_AXI")
    signals = evaluate_strategy_risk_rules(target, {"daily_dd_pct": None, "total_dd_pct": 7.7})
    by_key = {signal["rule_key"]: signal for signal in signals}
    assert set(by_key) == {"DD_TOTAL_50", "DD_TOTAL_70", "DD_TOTAL_90"}
    assert by_key["DD_TOTAL_50"]["severity"] == "medium"
    assert by_key["DD_TOTAL_70"]["severity"] == "high"
    assert by_key["DD_TOTAL_90"]["severity"] == "critical"


def test_daily_drawdown_levels_are_emitted_at_limit_fractions():
    registry = load_registry()
    target = pick(registry.strategies, "MONDAY_BTCJPY")
    signals = evaluate_strategy_risk_rules(target, {"daily_dd_pct": 3.5, "total_dd_pct": 0})
    assert [(item["rule_key"], item["severity"]) for item in signals] == [
        ("DD_DAILY_50", "medium"), ("DD_DAILY_70", "high")
    ]


def test_kill_switch_requires_restart_and_weekly_known_risk_is_permanent_info():
    registry = load_registry()
    weekly = pick(registry.strategies, "WEEKLYMOM_ETHUSD")
    signals = evaluate_strategy_risk_rules(
        weekly,
        {"daily_dd_pct": None, "total_dd_pct": 0},
        last_kill_at=NOW,
        last_started_at=NOW.replace(hour=19),
    )
    assert {(item["rule_key"], item["severity"]) for item in signals} == {
        ("KILL_ACTIVE", "critical"), ("KNOWN_RISK_WEEKLYMOM", "info")
    }
    cleared = evaluate_strategy_risk_rules(
        weekly,
        {"daily_dd_pct": None, "total_dd_pct": 0},
        last_kill_at=NOW.replace(hour=18),
        last_started_at=NOW,
    )
    assert [item["rule_key"] for item in cleared] == ["KNOWN_RISK_WEEKLYMOM"]


def test_portfolio_drawdown_and_broker_hard_limit_use_portfolio_scope():
    registry = load_registry()
    axi = pick(registry.portfolios, "P_AXI")
    signals = evaluate_portfolio_risk_rules(
        axi,
        {"daily_dd_pct": 2.5, "total_dd_pct": 8.2},
        daily_limit=registry.effective_portfolio_limit("P_AXI", "daily"),
        total_limit=registry.effective_portfolio_limit("P_AXI", "total"),
    )
    by_key = {signal["rule_key"]: signal for signal in signals}
    assert "PORTFOLIO_DD_DAILY_50" in by_key
    assert "PORTFOLIO_DD_TOTAL_90" in by_key
    assert by_key["BROKER_HARD_LIMIT"]["severity"] == "critical"
    assert by_key["BROKER_HARD_LIMIT"]["context"]["threshold_pct"] == 8.1


def test_portfolio_daily_dd_is_disabled_until_offset_is_known():
    registry = load_registry()
    axi = pick(registry.portfolios, "P_AXI")
    signals = evaluate_portfolio_risk_rules(axi, {"daily_dd_pct": None, "total_dd_pct": 0})
    assert signals == []
