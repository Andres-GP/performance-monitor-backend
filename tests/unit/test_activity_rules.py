from datetime import datetime, timedelta, timezone

from app.monitoring.activity_rules import evaluate_activity_rules
from app.monitoring.strategies import load_registry

UTC = timezone.utc
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


def strategy(registry, strategy_id):
    return next(item for item in registry.strategies if item.id == strategy_id)


def snapshot(**values):
    result = {
        "last_started_at": NOW - timedelta(hours=1),
        "current_mode": "demo",
        "recent_started_at": [NOW - timedelta(hours=1)],
        "health_events": [],
        "last_heartbeat_at": NOW,
        "last_equity_at": NOW,
        "last_trade_at": NOW - timedelta(days=1),
    }
    result.update(values)
    return result


def keys(alerts):
    return {alert["rule_key"] for alert in alerts}


def test_heartbeat_stale_escalates_from_high_to_critical():
    registry = load_registry()
    target = strategy(registry, "MONDAY_BTCJPY")
    high = evaluate_activity_rules(target, snapshot(last_heartbeat_at=NOW - timedelta(hours=2, minutes=1)), now=NOW)
    critical = evaluate_activity_rules(target, snapshot(last_heartbeat_at=NOW - timedelta(hours=4, minutes=1)), now=NOW)
    assert high[0]["rule_key"] == "HB_STALE" and high[0]["severity"] == "high"
    assert critical[0]["rule_key"] == "HB_STALE" and critical[0]["severity"] == "critical"


def test_equity_stale_only_fires_while_the_strategy_market_is_open():
    registry = load_registry()
    qqq = strategy(registry, "RSI2_QQQ")
    # 15:00 New York, regular session open; last equity was 20 minutes ago.
    alerts_open = evaluate_activity_rules(
        qqq,
        snapshot(last_equity_at=NOW - timedelta(minutes=20)),
        now=NOW,
    )
    # At 16:00 New York, QQQ is closed; same stale sample must not alert.
    closed_time = datetime(2026, 11, 19, 21, 0, tzinfo=UTC)
    alerts_closed = evaluate_activity_rules(
        qqq,
        snapshot(
            last_started_at=closed_time - timedelta(hours=1),
            last_equity_at=closed_time - timedelta(minutes=20),
            last_heartbeat_at=closed_time,
            last_trade_at=closed_time,
            recent_started_at=[closed_time - timedelta(hours=1)],
        ),
        now=closed_time,
    )
    assert "EQUITY_STALE" in keys(alerts_open)
    assert "EQUITY_STALE" not in keys(alerts_closed)


def test_ea_stopped_clears_after_restart_and_detects_restart_loop_and_mode_mismatch():
    registry = load_registry()
    target = strategy(registry, "GOTOBI_USDJPY_AXI")
    events = [{
        "received_at": (NOW - timedelta(minutes=10)).isoformat(),
        "payload": {"problem_type": "EAStopped"},
    }]
    after_restart = evaluate_activity_rules(
        target,
        snapshot(
            last_started_at=NOW - timedelta(minutes=5),
            recent_started_at=[NOW - timedelta(minutes=50), NOW - timedelta(minutes=20), NOW - timedelta(minutes=5)],
            health_events=events,
            current_mode="live",
        ),
        now=NOW,
    )
    assert "EA_STOPPED" not in keys(after_restart)
    assert {"RESTART_LOOP", "MODE_MISMATCH"} <= keys(after_restart)

    still_stopped = evaluate_activity_rules(
        target,
        snapshot(last_started_at=NOW - timedelta(minutes=15), health_events=events),
        now=NOW,
    )
    assert "EA_STOPPED" in keys(still_stopped)


def test_inactive_calendar_thresholds_match_strategy_bar_counts():
    registry = load_registry()
    gotobi = strategy(registry, "GOTOBI_USDJPY_AXI")
    monday = strategy(registry, "MONDAY_BTCJPY")
    gotobi_alerts = evaluate_activity_rules(
        gotobi,
        snapshot(last_trade_at=NOW - timedelta(days=17)),
        now=NOW,
    )
    monday_alerts = evaluate_activity_rules(
        monday,
        snapshot(last_trade_at=NOW - timedelta(days=29)),
        now=NOW,
    )
    assert "INACTIVE" in keys(gotobi_alerts)
    assert "INACTIVE" not in keys(monday_alerts)


def test_rsi2_inactivity_uses_completed_trading_sessions():
    registry = load_registry()
    qqq = strategy(registry, "RSI2_QQQ")
    recent = evaluate_activity_rules(
        qqq,
        snapshot(last_trade_at=datetime(2026, 10, 15, 14, tzinfo=UTC)),
        now=NOW,
    )
    old = evaluate_activity_rules(
        qqq,
        snapshot(last_trade_at=datetime(2026, 6, 1, 14, tzinfo=UTC)),
        now=NOW,
    )
    assert "INACTIVE" not in keys(recent)
    assert "INACTIVE" in keys(old)


def test_mode_normalization_accepts_reporter_simulation_label():
    registry = load_registry()
    target = strategy(registry, "RSI2_QQQ")
    alerts = evaluate_activity_rules(target, snapshot(current_mode="Simulation"), now=NOW)
    assert "MODE_MISMATCH" not in keys(alerts)
