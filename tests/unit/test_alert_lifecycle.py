from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.monitoring.alert_lifecycle import (
    acknowledge_alert,
    deliver_due_alerts,
    notification_due,
    reconcile_alerts,
)


UTC = timezone.utc
NOW = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)


class MemoryAlertRepository:
    def __init__(self, alerts=None):
        self.alerts = deepcopy(alerts or [])
        self.states = {}

    def active_alerts(self, rule_keys):
        return [row for row in self.alerts if row["rule_key"] in rule_keys and row["status"] in {"open", "ack"}]

    def open_alerts(self):
        return [row for row in self.alerts if row["status"] == "open"]

    def get_rule_state(self, rule_key, scope_type, scope_id):
        return deepcopy(self.states.get((rule_key, scope_type, scope_id)))

    def save_rule_state(self, record):
        self.states[(record["rule_key"], record["scope_type"], record["scope_id"])] = deepcopy(record)

    def resolve_alert(self, alert_id, at):
        row = next(row for row in self.alerts if row["id"] == alert_id)
        row.update(status="resolved", resolved_at=at.isoformat())

    def acknowledge_alert(self, alert_id, at):
        row = next(row for row in self.alerts if row["id"] == alert_id)
        row.update(status="ack", ack_at=at.isoformat())


def alert(rule_key="HB_STALE", severity="high", status="open", **extra):
    return {
        "id": 1,
        "rule_key": rule_key,
        "strategy_id": "MONDAY_BTCJPY",
        "portfolio_id": None,
        "severity": severity,
        "status": status,
        "context": {"age_hours": 3, "threshold_hours": 2},
        **extra,
    }


def test_alert_auto_resolves_after_two_clean_evaluations():
    repo = MemoryAlertRepository([alert()])
    assert reconcile_alerts(repo, [], {"HB_STALE"}, now=NOW) == []
    assert repo.alerts[0]["status"] == "open"
    assert reconcile_alerts(repo, [], {"HB_STALE"}, now=NOW + timedelta(minutes=1)) == [1]
    assert repo.alerts[0]["status"] == "resolved"


def test_active_signal_resets_clean_passes_and_kill_switch_needs_manual_ack():
    repo = MemoryAlertRepository([alert(), alert("KILL_ACTIVE", "critical", id=2)])
    repo.save_rule_state({
        "rule_key": "HB_STALE", "scope_type": "strategy", "scope_id": "MONDAY_BTCJPY",
        "consecutive_passes": 1, "state": {},
    })
    active = [alert()]
    reconcile_alerts(repo, active, {"HB_STALE", "KILL_ACTIVE"}, now=NOW)
    assert repo.states[("HB_STALE", "strategy", "MONDAY_BTCJPY")]["consecutive_passes"] == 0
    reconcile_alerts(repo, [], {"HB_STALE", "KILL_ACTIVE"}, now=NOW + timedelta(minutes=1))
    assert repo.alerts[1]["status"] == "open"

    acknowledge_alert(repo, 2, now=NOW + timedelta(minutes=2))
    assert repo.alerts[1]["status"] == "ack"
    reconcile_alerts(repo, [], {"KILL_ACTIVE"}, now=NOW + timedelta(minutes=3))
    assert repo.alerts[1]["status"] == "ack"


def test_severity_cooldowns_and_ack_state():
    assert notification_due(alert(severity="critical"), NOW, None)
    assert not notification_due(alert(severity="critical"), NOW + timedelta(minutes=29), NOW)
    assert notification_due(alert(severity="critical"), NOW + timedelta(minutes=30), NOW)
    assert not notification_due(alert(severity="high"), NOW + timedelta(hours=5, minutes=59), NOW)
    assert notification_due(alert(severity="high"), NOW + timedelta(hours=6), NOW)
    assert notification_due(alert(severity="medium"), NOW, None)
    assert not notification_due(alert(severity="medium"), NOW + timedelta(hours=1), NOW)
    assert not notification_due(alert(severity="info"), NOW, None)
    assert not notification_due(alert(status="ack"), NOW, None)


def test_medium_alerts_are_sent_as_one_daily_summary_and_marked_notified():
    repo = MemoryAlertRepository([
        alert("DD_DAILY_50", "medium", id=1),
        alert("PF_DRIFT", "medium", id=2, strategy_id="GOTOBI_USDJPY_AXI"),
        alert("KNOWN_RISK_WEEKLYMOM", "info", id=3),
        alert("KILL_ACTIVE", "critical", id=4, strategy_id="WEEKLYMOM_ETHUSD"),
    ])
    messages = []
    sent = deliver_due_alerts(repo, now=NOW, webhook_url="https://example.invalid/hook", sender=lambda url, message: messages.append((url, message)))
    assert len(sent) == 3
    assert len(messages) == 2  # One critical message plus one medium digest.
    digest = next(message for _, message in messages if "Daily monitoring summary" in message)
    assert "DD_DAILY_50" in digest and "PF_DRIFT" in digest
    assert all("last_notified_at" in state for state in repo.states.values())
