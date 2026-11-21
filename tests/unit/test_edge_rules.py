from datetime import datetime, timedelta, timezone

from app.monitoring.edge_rules import evaluate_edge_decay
from app.monitoring.strategies import Baselines, load_registry


UTC = timezone.utc
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


def strategy(registry, strategy_id, baselines):
    original = next(item for item in registry.strategies if item.id == strategy_id)
    return original.model_copy(update={"baselines": Baselines.model_validate(baselines)})


def test_edge_rules_report_insufficient_data_below_twenty_trades():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY", {"bt_win_rate": 0.6})
    result = evaluate_edge_decay(
        target,
        {"rolling_50": {"n_trades": 19}},
        [],
        now=NOW,
    )
    assert result == {"state": "INSUFFICIENT_DATA", "n_trades": 19, "signals": []}


def test_no_backtest_baselines_produce_no_edge_alerts():
    registry = load_registry()
    target = next(item for item in registry.strategies if item.id == "MONDAY_BTCJPY")
    result = evaluate_edge_decay(
        target,
        {"rolling_50": {"n_trades": 50, "win_rate": 10}},
        [],
        now=NOW,
    )
    assert result == {"state": "NO_BASELINE", "n_trades": 50, "signals": []}


def test_live_decision_rules_work_without_backtest_baseline():
    registry = load_registry()
    target = next(item for item in registry.strategies if item.id == "MONDAY_BTCJPY")
    result = evaluate_edge_decay(target, {
        "rolling_50": {
            "n_trades": 50,
            "average_net_per_trade": -2.5,
            "profit_factor": 1.02,
            "t_stat_net_per_trade": 0.8,
        },
    }, [], now=NOW)
    assert result["state"] == "NO_BASELINE"
    signals = {item["rule_key"]: item for item in result["signals"]}
    assert {"PAUSE_NEGATIVE_NET_MEAN", "DISCARD_CANDIDATE_LOW_PF", "DISCARD_CANDIDATE_LOW_T_STAT"} <= set(signals)
    assert "automatic action" in signals["PAUSE_NEGATIVE_NET_MEAN"]["context"]["recommendation"]


def test_wr_pf_expectancy_cost_and_loss_streak_rules_include_sample_size():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY", {
        "bt_win_rate": 0.6,
        "bt_profit_factor": 1.5,
        "bt_cost_ratio": 0.01,
        "bt_max_loss_streak": 3,
    })
    trades = [{
        "exit_time": NOW - timedelta(days=day),
        "profit": 4,
        "commission": -1,
        "swap": -1,
    } for day in range(20)]
    result = evaluate_edge_decay(target, {
        "rolling_50": {
            "n_trades": 20,
            "win_rate": 20,
            "profit_factor": 0.5,
            "expectancy_pct": -0.1,
            "current_loss_streak": 4,
        },
    }, trades, now=NOW)
    by_key = {signal["rule_key"]: signal for signal in result["signals"]}
    assert {"WR_DRIFT", "PF_DRIFT", "EXPECTANCY_NEG", "COST_DRIFT", "LOSS_STREAK"} == set(by_key)
    assert all(signal["context"]["n_trades"] == 20 for signal in by_key.values())


def test_frequency_drift_uses_three_month_window():
    registry = load_registry()
    target = strategy(registry, "WEEKLYMOM_ETHUSD", {"bt_trades_per_month": 2})
    old_trades = [{"exit_time": NOW - timedelta(days=100 + day)} for day in range(20)]
    result = evaluate_edge_decay(target, {
        "rolling_50": {"n_trades": 20},
    }, old_trades, now=NOW)
    signal = next(item for item in result["signals"] if item["rule_key"] == "FREQ_DRIFT")
    assert signal["context"]["live_trades_per_month"] == 0
    assert signal["context"]["window_days"] == 90


def test_rsi2_uses_twenty_trade_window():
    registry = load_registry()
    target = strategy(registry, "RSI2_QQQ", {"bt_profit_factor": 2})
    result = evaluate_edge_decay(target, {
        "rolling_20": {"n_trades": 20, "profit_factor": 0.9},
        "rolling_50": {"n_trades": 50, "profit_factor": 2},
    }, [], now=NOW)
    assert result["n_trades"] == 20
    assert [item["rule_key"] for item in result["signals"]] == ["PF_DRIFT"]
