"""Alert dedupe lifecycle, evaluation-based resolution, and webhook cooldowns."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

UTC = timezone.utc


class AlertLifecycleRepository(Protocol):
    def active_alerts(self, rule_keys: set[str]) -> list[dict[str, Any]]: ...
    def open_alerts(self) -> list[dict[str, Any]]: ...
    def get_rule_state(self, rule_key: str, scope_type: str, scope_id: str) -> dict[str, Any] | None: ...
    def save_rule_state(self, record: dict[str, Any]) -> None: ...
    def resolve_alert(self, alert_id: int | str, at: datetime) -> None: ...
    def acknowledge_alert(self, alert_id: int | str, at: datetime) -> None: ...


class SupabaseAlertLifecycleRepository:
    def __init__(self, client):
        if client is None:
            raise RuntimeError("Supabase client is not configured")
        self.client = client

    def active_alerts(self, rule_keys):
        if not rule_keys:
            return []
        return (
            self.client.table("alert").select("*")
            .in_("rule_key", sorted(rule_keys)).in_("status", ["open", "ack"])
            .execute().data or []
        )

    def open_alerts(self):
        return self.client.table("alert").select("*").eq("status", "open").execute().data or []

    def get_rule_state(self, rule_key, scope_type, scope_id):
        rows = (
            self.client.table("rule_state").select("*")
            .eq("rule_key", rule_key).eq("scope_type", scope_type).eq("scope_id", scope_id)
            .limit(1).execute().data or []
        )
        return rows[0] if rows else None

    def save_rule_state(self, record):
        self.client.table("rule_state").upsert(
            record, on_conflict="rule_key,scope_type,scope_id"
        ).execute()

    def resolve_alert(self, alert_id, at):
        self.client.table("alert").update({
            "status": "resolved", "resolved_at": at.isoformat(),
        }).eq("id", alert_id).in_("status", ["open", "ack"]).execute()

    def acknowledge_alert(self, alert_id, at):
        self.client.table("alert").update({
            "status": "ack", "ack_at": at.isoformat(),
        }).eq("id", alert_id).eq("status", "open").execute()


def _scope(alert: dict[str, Any]) -> tuple[str, str]:
    if alert.get("strategy_id") is not None:
        return "strategy", str(alert["strategy_id"])
    if alert.get("portfolio_id") is not None:
        return "portfolio", str(alert["portfolio_id"])
    return "portfolio", "GLOBAL"


def _alert_key(alert: dict[str, Any]) -> tuple[str, str | None, str | None]:
    return alert["rule_key"], alert.get("strategy_id"), alert.get("portfolio_id")


def _save_state(repository, alert, now, *, consecutive_passes=None, last_notified_at=None):
    rule_key = alert["rule_key"]
    scope_type, scope_id = _scope(alert)
    existing = repository.get_rule_state(rule_key, scope_type, scope_id) or {}
    state = dict(existing.get("state") or {})
    if consecutive_passes is not None:
        state["consecutive_passes"] = consecutive_passes
    payload = {
        "rule_key": rule_key,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "last_evaluated_at": now.isoformat(),
        "consecutive_failures": 0,
        "consecutive_passes": (
            consecutive_passes if consecutive_passes is not None
            else int(existing.get("consecutive_passes") or 0)
        ),
        "state": state,
    }
    if last_notified_at is not None:
        payload["last_notified_at"] = last_notified_at.isoformat()
    elif existing.get("last_notified_at"):
        payload["last_notified_at"] = existing["last_notified_at"]
    repository.save_rule_state(payload)


def reconcile_alerts(
    repository: AlertLifecycleRepository,
    active_signals: list[dict[str, Any]],
    evaluated_rule_keys: set[str],
    *,
    now: datetime,
) -> list[int | str]:
    """Resolve an alert after two clean evaluations, except acknowledged KillSwitch."""
    if now.tzinfo is None:
        raise ValueError("alert lifecycle requires an aware timestamp")
    now = now.astimezone(UTC)
    current = {_alert_key(signal) for signal in active_signals}
    resolved = []
    for alert in repository.active_alerts(evaluated_rule_keys):
        key = _alert_key(alert)
        if key in current:
            _save_state(repository, alert, now, consecutive_passes=0)
            continue
        if alert["rule_key"] == "KILL_ACTIVE":
            continue
        scope_type, scope_id = _scope(alert)
        state = repository.get_rule_state(alert["rule_key"], scope_type, scope_id) or {}
        passes = int(state.get("consecutive_passes") or 0) + 1
        _save_state(repository, alert, now, consecutive_passes=passes)
        if passes >= 2:
            repository.resolve_alert(alert["id"], now)
            resolved.append(alert["id"])
    return resolved


def notification_due(alert: dict[str, Any], now: datetime, last_notified_at: datetime | str | None) -> bool:
    if alert.get("status") != "open":
        return False
    severity = str(alert.get("severity", "")).lower()
    if severity == "info":
        return False
    last = _as_utc(last_notified_at)
    if severity == "critical":
        return last is None or now - last >= timedelta(minutes=30)
    if severity == "high":
        return last is None or now - last >= timedelta(hours=6)
    if severity == "medium":
        return now.hour == 8 and (last is None or last.date() < now.date())
    return False


def acknowledge_alert(repository: AlertLifecycleRepository, alert_id: int | str, *, now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("alert acknowledgement requires an aware timestamp")
    repository.acknowledge_alert(alert_id, now.astimezone(UTC))


def format_alert_message(alert: dict[str, Any], *, now: datetime) -> str:
    scope = alert.get("portfolio_id") or alert.get("strategy_id") or "monitor"
    context = alert.get("context") or {}
    value = context.get("drawdown_pct", context.get("correlation", context.get("age_hours")))
    threshold = context.get("limit_pct", context.get("threshold_pct", context.get("threshold_hours")))
    comparison = f"{value} vs {threshold}" if value is not None and threshold is not None else str(context)
    return f"[{alert['severity'].upper()}] {scope} — {alert['rule_key']} — {comparison} — {now.astimezone(UTC).isoformat()} UTC"


def _send_webhook(url: str, message: str) -> None:
    response = httpx.post(url, json={"text": message}, timeout=10.0)
    response.raise_for_status()


def deliver_due_alerts(
    repository: AlertLifecycleRepository,
    *,
    now: datetime,
    webhook_url: str | None = None,
    sender=_send_webhook,
) -> list[dict[str, Any]]:
    if now.tzinfo is None:
        raise ValueError("alert delivery requires an aware timestamp")
    now = now.astimezone(UTC)
    webhook_url = webhook_url if webhook_url is not None else os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url:
        return []
    due = []
    for alert in repository.open_alerts():
        scope_type, scope_id = _scope(alert)
        state = repository.get_rule_state(alert["rule_key"], scope_type, scope_id) or {}
        if notification_due(alert, now, state.get("last_notified_at")):
            due.append(alert)
    medium = [item for item in due if item["severity"].lower() == "medium"]
    sent: list[dict[str, Any]] = []
    urgent = [item for item in due if item["severity"].lower() in {"critical", "high"}]
    for alert in urgent:
        sender(webhook_url, format_alert_message(alert, now=now))
        _save_state(repository, alert, now, last_notified_at=now)
        sent.append(alert)
    if medium:
        lines = ["[MEDIUM] Daily monitoring summary — " + now.isoformat() + " UTC"]
        lines.extend(format_alert_message(item, now=now) for item in medium)
        sender(webhook_url, "\n".join(lines))
        for alert in medium:
            _save_state(repository, alert, now, last_notified_at=now)
            sent.append(alert)
    return sent


def run_alert_lifecycle(client, *, active_signals, evaluated_rule_keys, now=None, webhook_url=None):
    now = now or datetime.now(UTC)
    repository = SupabaseAlertLifecycleRepository(client)
    resolved = reconcile_alerts(repository, active_signals, evaluated_rule_keys, now=now)
    notified = deliver_due_alerts(repository, now=now, webhook_url=webhook_url)
    return {"resolved_ids": resolved, "notified": notified}


def _as_utc(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
