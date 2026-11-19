from datetime import datetime, timezone

from app.monitoring.conformity import evaluate_closed_trade
from app.monitoring.strategies import load_registry


UTC = timezone.utc


def strategy(registry, strategy_id):
    return next(item for item in registry.strategies if item.id == strategy_id)


def closed_trade(entry, exit_, direction="long", volume=0.1, price=100):
    return {
        "entry_time": entry,
        "exit_time": exit_,
        "trade_type": direction,
        "volume": volume,
        "entry_price": price,
    }


def test_monday_trade_within_schedule_and_hold_tolerance_is_compliant():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY")
    signals = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 9, 0, 10, tzinfo=UTC), datetime(2026, 11, 10, 0, 10, tzinfo=UTC)),
    )
    assert signals == []


def test_direction_hold_schedule_and_first_monday_filter_signals():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY")
    signals = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 2, 0, 20, tzinfo=UTC), datetime(2026, 11, 3, 2, 0, tzinfo=UTC), "short"),
    )
    by_key = {signal["rule_key"]: signal for signal in signals}
    assert {"DIR_VIOLATION", "HOLD_DEVIATION", "ENTRY_OFF_SCHEDULE", "ENTRY_ON_FILTERED_DAY"} <= set(by_key)
    assert by_key["DIR_VIOLATION"]["severity"] == "critical"


def test_gotobi_checks_next_calendar_date_and_excluded_dates():
    registry = load_registry()
    target = strategy(registry, "GOTOBI_USDJPY_AXI")
    invalid = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 8, 22, 30, tzinfo=UTC), datetime(2026, 11, 9, 0, 55, tzinfo=UTC)),
    )
    valid = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 9, 22, 30, tzinfo=UTC), datetime(2026, 11, 10, 0, 55, tzinfo=UTC)),
    )
    assert "ENTRY_ON_FILTERED_DAY" in {signal["rule_key"] for signal in invalid}
    assert not any(signal["rule_key"].startswith("ENTRY_") for signal in valid)


def test_weekly_momentum_schedule_is_checked_in_broker_server_time():
    registry = load_registry()
    target = strategy(registry, "WEEKLYMOM_ETHUSD")
    good = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 8, 22, 4, tzinfo=UTC), datetime(2026, 11, 19, 22, 4, tzinfo=UTC)),
        server_offset_hours=2,
    )
    bad = evaluate_closed_trade(
        target,
        closed_trade(datetime(2026, 11, 8, 21, 50, tzinfo=UTC), datetime(2026, 11, 19, 21, 50, tzinfo=UTC)),
        server_offset_hours=2,
    )
    assert not any(signal["rule_key"] == "ENTRY_OFF_SCHEDULE" for signal in good)
    assert any(signal["rule_key"] == "ENTRY_OFF_SCHEDULE" for signal in bad)


def test_concurrency_reconstructs_overlapping_positions_and_size_disables_without_contract():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY")
    current = closed_trade(datetime(2026, 11, 9, 0, 0, tzinfo=UTC), datetime(2026, 11, 10, 0, 0, tzinfo=UTC))
    previous = closed_trade(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    signals = evaluate_closed_trade(
        target, current, equity_at_open=1000, overlapping_trades=[previous],
    )
    assert {signal["rule_key"] for signal in signals} == {"CONCURRENCY"}
