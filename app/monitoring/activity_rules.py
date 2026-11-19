"""Life and activity checks (Step 5) over normalized monitoring records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .ingestion import SupabaseMonitoringRepository
from .market_hours import completed_trading_sessions, market_is_open
from .strategies import Strategy, StrategyRegistry

UTC = timezone.utc


class ActivityRepository(Protocol):
    def activity_snapshot(self, strategy_id: str, since: datetime) -> dict[str, Any]: ...


class SupabaseActivityRepository:
    """Read compact latest-event snapshots from the monitoring tables."""

    def __init__(self, client):
        if client is None:
            raise RuntimeError("Supabase client is not configured")
        self.client = client

    def _latest(self, table: str, strategy_id: str, timestamp_column: str) -> dict[str, Any] | None:
        rows = (
            self.client.table(table)
            .select("*")
            .eq("strategy_id", strategy_id)
            .order(timestamp_column, desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    def activity_snapshot(self, strategy_id: str, since: datetime) -> dict[str, Any]:
        latest_start = (
            self.client.table("event_raw")
            .select("ts,received_at,payload")
            .eq("strategy_id", strategy_id)
            .eq("event_type", "strategy_started")
            .order("received_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        recent_starts = (
            self.client.table("event_raw")
            .select("ts,received_at,payload")
            .eq("strategy_id", strategy_id)
            .eq("event_type", "strategy_started")
            .gte("received_at", since.isoformat())
            .execute()
            .data
            or []
        )
        health_events = (
            self.client.table("event_raw")
            .select("ts,received_at,payload")
            .eq("strategy_id", strategy_id)
            .eq("event_type", "health_alert")
            .order("received_at", desc=True)
            .limit(200)
            .execute()
            .data
            or []
        )
        stopped_records = []
        for field in ("type", "problem_type"):
            for stopped_value in ("EAStopped", "EA_STOPPED"):
                records = (
                    self.client.table("event_raw")
                    .select("received_at")
                    .eq("strategy_id", strategy_id)
                    .eq("event_type", "health_alert")
                    .filter(f"payload->>{field}", "eq", stopped_value)
                    .order("received_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                stopped_records.extend(records)
        latest_heartbeat = self._latest("heartbeat", strategy_id, "ts")
        latest_equity = self._latest("equity_sample", strategy_id, "ts")
        latest_trade = self._latest("trade", strategy_id, "exit_time")
        start = latest_start[0] if latest_start else None
        return {
            "last_started_at": (start or {}).get("received_at"),
            "current_mode": _mode_from_payload((start or {}).get("payload", {})),
            "recent_started_at": [row.get("received_at") for row in recent_starts],
            "health_events": health_events,
            "last_ea_stopped_at": max(
                (row["received_at"] for row in stopped_records if row.get("received_at")),
                default=None,
            ),
            "last_heartbeat_at": (latest_heartbeat or {}).get("ts"),
            "last_equity_at": (latest_equity or {}).get("ts"),
            "last_trade_at": (latest_trade or {}).get("exit_time"),
        }


def _as_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_mode(value: Any) -> str | None:
    if value is None:
        return None
    mode = str(value).strip().lower()
    if "demo" in mode or "simulat" in mode or mode in {"paper", "test"}:
        return "demo"
    if "live" in mode or "real" in mode:
        return "live"
    return None


def _mode_from_payload(payload: dict[str, Any]) -> str | None:
    return _normalize_mode(payload.get("mode") or payload.get("data_type"))


def _health_event_type(payload: dict[str, Any]) -> str:
    value = payload.get("type") or payload.get("problem_type") or payload.get("alert_type") or ""
    return str(value).strip().upper().replace(" ", "_").replace("-", "_")


def _inactivity_threshold(strategy: Strategy) -> tuple[str, int]:
    if strategy.id == "RSI2_QQQ":
        return "trading_sessions", strategy.max_bars_no_trade
    timeframe = strategy.timeframe.upper()
    if timeframe.startswith("M"):
        minutes_per_bar = int(timeframe[1:])
    elif timeframe.startswith("H"):
        minutes_per_bar = int(timeframe[1:]) * 60
    elif timeframe.startswith("D"):
        minutes_per_bar = 1440
    else:
        return "calendar_days", 0
    bars_per_day = 1440 / minutes_per_bar
    return "calendar_days", int(strategy.max_bars_no_trade / bars_per_day)


def evaluate_activity_rules(
    strategy: Strategy,
    snapshot: dict[str, Any],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return active life/activity alerts for one strategy at a fixed instant."""
    if now.tzinfo is None:
        raise ValueError("activity evaluation requires an aware timestamp")
    now = now.astimezone(UTC)
    alerts: list[dict[str, Any]] = []

    def add(rule_key: str, severity: str, context: dict[str, Any]):
        alerts.append({
            "rule_key": rule_key,
            "strategy_id": strategy.id,
            "severity": severity,
            "context": context,
        })

    started_at = _as_utc(snapshot.get("last_started_at"))
    heartbeat_at = _as_utc(snapshot.get("last_heartbeat_at")) or started_at
    if heartbeat_at is not None:
        age_hours = (now - heartbeat_at).total_seconds() / 3600
        if age_hours > 4:
            add("HB_STALE", "critical", {"age_hours": age_hours, "threshold_hours": 4})
        elif age_hours > 2:
            add("HB_STALE", "high", {"age_hours": age_hours, "threshold_hours": 2})

    equity_reference = _as_utc(snapshot.get("last_equity_at")) or started_at
    is_open = market_is_open(strategy.market_calendar, now)
    if is_open is True and equity_reference is not None:
        age_minutes = (now - equity_reference).total_seconds() / 60
        if age_minutes > 15:
            add("EQUITY_STALE", "high", {"age_minutes": age_minutes, "threshold_minutes": 15})

    last_started = started_at
    latest_stop = _as_utc(snapshot.get("last_ea_stopped_at"))
    if latest_stop is None:
        ea_stops = [
            _as_utc(event.get("received_at"))
            for event in snapshot.get("health_events", [])
            if _health_event_type(event.get("payload") or {}) in {"EASTOPPED", "EA_STOPPED"}
        ]
        latest_stop = max((event_time for event_time in ea_stops if event_time is not None), default=None)
    if latest_stop is not None and (last_started is None or latest_stop >= last_started):
        add("EA_STOPPED", "high", {"stopped_at": latest_stop.isoformat()})

    recent_starts = [
        event_time
        for event_time in (_as_utc(value) for value in snapshot.get("recent_started_at", []))
        if event_time is not None and now - timedelta(hours=1) <= event_time <= now
    ]
    if len(recent_starts) >= 3:
        add("RESTART_LOOP", "high", {"starts_last_hour": len(recent_starts), "threshold": 3})

    current_mode = _normalize_mode(snapshot.get("current_mode"))
    if current_mode and current_mode != strategy.expected_mode:
        add("MODE_MISMATCH", "medium", {
            "actual_mode": current_mode,
            "expected_mode": strategy.expected_mode,
        })

    trade_at = _as_utc(snapshot.get("last_trade_at"))
    inactivity_anchor = trade_at or started_at
    if inactivity_anchor is not None:
        threshold_kind, threshold = _inactivity_threshold(strategy)
        if threshold_kind == "trading_sessions":
            elapsed = completed_trading_sessions(strategy.market_calendar, inactivity_anchor, now)
            if elapsed > threshold:
                add("INACTIVE", "high", {
                    "elapsed_trading_sessions": elapsed,
                    "threshold_trading_sessions": threshold,
                    "anchor": inactivity_anchor.isoformat(),
                })
        else:
            elapsed_days = (now - inactivity_anchor).total_seconds() / 86400
            if threshold > 0 and elapsed_days > threshold:
                add("INACTIVE", "high", {
                    "elapsed_days": elapsed_days,
                    "threshold_days": threshold,
                    "anchor": inactivity_anchor.isoformat(),
                })
    return alerts


def run_activity_rules(
    client,
    registry: StrategyRegistry,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    activity_repository = SupabaseActivityRepository(client)
    alert_repository = SupabaseMonitoringRepository(client)
    alerts: list[dict[str, Any]] = []
    for strategy in registry.strategies:
        snapshot = activity_repository.activity_snapshot(strategy.id, now - timedelta(hours=1))
        signals = evaluate_activity_rules(strategy, snapshot, now=now)
        for signal in signals:
            record = {
                **signal,
                "portfolio_id": None,
                "status": "open",
                "first_seen": now.isoformat(),
                "last_seen": now.isoformat(),
                "count": 1,
            }
            alert_repository.insert_alert(record)
            alerts.append(record)
    return alerts
