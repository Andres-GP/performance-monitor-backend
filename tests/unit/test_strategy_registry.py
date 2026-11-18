from pathlib import Path

import pytest
from pydantic import ValidationError

from app.monitoring.strategies import (
    StrategyRegistry,
    baseline_rule_enabled,
    load_registry,
)


@pytest.fixture
def registry():
    return load_registry()


def test_registry_loads_all_portfolios_strategies_and_preserves_null_baselines(registry):
    assert {p.id for p in registry.portfolios} == {"P_AXI", "P_DWX"}
    assert {s.id for s in registry.strategies} == {
        "MONDAY_BTCJPY", "GOTOBI_USDJPY_AXI", "WEEKLYMOM_ETHUSD", "GOTOBI_USDJPY_DWX", "RSI2_QQQ"
    }
    assert all(s.baselines.bt_win_rate is None for s in registry.strategies)
    assert registry.portfolios[0].server_utc_offset_hours is None
    assert not registry.portfolios[0].server_time_to_utc_enabled


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ALPHACA_MONDAY_BTCJPY.a", "MONDAY_BTCJPY"),
        ("ALPHACA_GOTOBI_USDJPYx", "GOTOBI_USDJPY_AXI"),
        ("ALPHACA_GOTOBI_DWX_USDJPY", "GOTOBI_USDJPY_DWX"),
        ("TIS_RSI2_QQQ", "RSI2_QQQ"),
        ("OTHER_STRATEGY", None),
    ],
)
def test_match_strategy_by_prefix(registry, name, expected):
    strategy = registry.match_strategy(name)
    assert (strategy.id if strategy else None) == expected


def test_portfolio_limit_uses_strictest_strategy_limit(registry):
    assert registry.effective_portfolio_limit("P_AXI", "daily") == 5.0
    assert registry.effective_portfolio_limit("P_DWX", "daily") == 3.0
    assert registry.effective_portfolio_limit("P_DWX", "total") == 8.0


def test_baseline_rules_stay_disabled_when_value_is_null(registry):
    strategy = registry.match_strategy("ALPHACA_MONDAY_BTCJPY")
    assert not baseline_rule_enabled(strategy, "bt_max_dd_pct")


def test_baseline_rule_can_be_enabled_when_value_is_supplied(tmp_path: Path):
    source = Path(__file__).parents[2] / "config" / "strategies.yaml"
    yaml_text = source.read_text(encoding="utf-8").replace("bt_max_dd_pct: null", "bt_max_dd_pct: 12.5", 1)
    config_path = tmp_path / "strategies.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")
    strategy = load_registry(config_path).match_strategy("ALPHACA_MONDAY_BTCJPY")
    assert baseline_rule_enabled(strategy, "bt_max_dd_pct")


def test_unknown_portfolio_reference_fails_validation():
    data = load_registry().model_dump()
    data["strategies"][0]["portfolio_id"] = "MISSING"
    with pytest.raises(ValidationError, match="unknown portfolios"):
        StrategyRegistry.model_validate(data)
