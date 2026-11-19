from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.monitoring.ingestion import (
    EventValidationError,
    ingest_event,
    server_time_to_utc,
)
from app.monitoring.strategies import load_registry


class MemoryRepository:
    def __init__(self):
        self.raw_events = []
        self.raw_keys = set()
        self.unregistered_sources = {}
        self.alerts = []
        self.equities = {}
        self.trades = []
        self.heartbeats = []

    def insert_event_raw(self, record):
        key = record.get("idempotency_key")
        if key and key in self.raw_keys:
            saved = next(raw for raw in self.raw_events if raw.get("idempotency_key") == key)
            return False, saved["id"], saved["ingest_status"]
        if key:
            self.raw_keys.add(key)
        saved = deepcopy(record)
        saved["id"] = len(self.raw_events) + 1
        self.raw_events.append(saved)
        return True, saved["id"], "received"

    def set_event_status(self, raw_id, status, ts=None):
        if raw_id is None:
            return
        raw = self.raw_events[int(raw_id) - 1]
        raw["ingest_status"] = status
        if ts is not None:
            raw["ts"] = ts.isoformat()

    def find_strategy_alias(self, external_id):
        for raw in reversed(self.raw_events):
            if raw["event_type"] == "strategy_started" and raw["payload"].get("strategy_id") == external_id:
                return raw.get("strategy_id")
        return None

    def upsert_unregistered_source(self, record):
        key = (record.get("source_name"), record.get("source_magic"))
        current = self.unregistered_sources.get(key)
        updated = deepcopy(record)
        updated["occurrences"] = current["occurrences"] + 1 if current else 1
        self.unregistered_sources[key] = updated

    def insert_alert(self, record):
        active = next((
            alert for alert in self.alerts
            if alert["rule_key"] == record["rule_key"]
            and alert.get("strategy_id") == record.get("strategy_id")
            and alert.get("portfolio_id") == record.get("portfolio_id")
            and alert["status"] in {"open", "ack"}
        ), None)
        if active:
            active["count"] += record.get("count", 1)
            active["last_seen"] = record["last_seen"]
            active["context"] = deepcopy(record["context"])
        else:
            self.alerts.append(deepcopy(record))

    @staticmethod
    def _dt(value):
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def find_equity_sample(self, strategy_id, ts):
        record = self.equities.get((strategy_id, ts.isoformat()))
        return deepcopy(record) if record else None

    def find_previous_equity(self, strategy_id, ts):
        candidates = [
            value for (sid, _), value in self.equities.items()
            if sid == strategy_id and self._dt(value["ts"]) < ts
        ]
        return deepcopy(max(candidates, key=lambda value: self._dt(value["ts"]))) if candidates else None

    def has_closed_trade_between(self, strategy_id, start, end):
        return any(
            trade["strategy_id"] == strategy_id
            and start <= self._dt(trade["exit_time"]) <= end
            for trade in self.trades
        )

    def has_open_position(self, strategy_id, ts):
        return False

    def upsert_equity_sample(self, record):
        self.equities[(record["strategy_id"], record["ts"])] = deepcopy(record)

    def upsert_trade(self, record):
        self.trades.append(deepcopy(record))

    def overlapping_trades(self, strategy_id, entry_time, exit_time):
        return [
            deepcopy(trade) for trade in self.trades
            if trade["strategy_id"] == strategy_id
            and self._dt(trade["entry_time"]) < exit_time
            and self._dt(trade["exit_time"]) > entry_time
        ]

    def recent_order_rejections(self, strategy_id, since):
        return [
            deepcopy(raw) for raw in self.raw_events
            if raw["strategy_id"] == strategy_id
            and raw["event_type"] == "order_rejected"
            and self._dt(raw["received_at"]) >= since
        ]

    def insert_heartbeat(self, record):
        self.heartbeats.append(deepcopy(record))


@pytest.fixture
def registry_with_offset():
    registry = load_registry()
    portfolios = [
        portfolio.model_copy(update={"server_utc_offset_hours": 2.0, "server_utc_offset_verified": True})
        if portfolio.id == "P_AXI" else portfolio
        for portfolio in registry.portfolios
    ]
    return registry.model_copy(update={"portfolios": portfolios})


def test_server_time_is_converted_using_verified_portfolio_offset():
    normalized = server_time_to_utc("2026-11-18T10:30:00Z", 2)
    assert normalized.isoformat() == "2026-11-18T08:30:00+00:00"


def test_trade_event_is_raw_idempotent_normalized_and_calculated(registry_with_offset):
    repository = MemoryRepository()
    repository.equities[("MONDAY_BTCJPY", "2026-11-15T21:59:00+00:00")] = {
        "strategy_id": "MONDAY_BTCJPY",
        "ts": "2026-11-15T21:59:00+00:00",
        "equity": 5000,
        "cashflow_suspected": False,
    }
    start = {
        "strategy_id": "ea-instance-1",
        "name": "ALPHACA_MONDAY_BTCJPY.a",
        "instrument": "BTCJPY.a",
        "timeframe": "H1",
        "data_type": "demo",
        "start_date": "2026-11-16T00:00:00Z",
    }
    started = ingest_event("strategy_started", start, repository, registry_with_offset)
    assert started == {"status": "processed", "strategy_id": "MONDAY_BTCJPY"}

    trade = {
        "strategy_id": "ea-instance-1",
        "instrument": "BTCJPY.a",
        "entry_time": "2026-11-16T00:00:00Z",
        "exit_time": "2026-11-17T00:00:00Z",
        "quantity": 0.2,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 10.0,
        "cost": 0.5,
        "direction": "Long",
    }
    result = ingest_event("trade_closed", trade, repository, registry_with_offset)
    duplicate = ingest_event("trade_closed", trade, repository, registry_with_offset)

    assert result["status"] == "processed"
    assert duplicate["status"] == "duplicate"
    assert len(repository.raw_events) == 2
    assert len(repository.trades) == 1
    assert repository.trades[0]["entry_time"] == "2026-11-15T22:00:00+00:00"
    assert repository.trades[0]["hold_minutes"] == 1440
    assert repository.trades[0]["trade_type"] == "long"
    assert repository.trades[0]["ticket"] is None
    assert repository.trades[0]["pnl_pct_equity"] == 0.2
    assert repository.trades[0]["duration_deviation_minutes"] == 0
    assert repository.raw_events[-1]["ts"] == "2026-11-16T22:00:00+00:00"


def test_trade_ingestion_opens_conformity_alerts(registry_with_offset):
    repository = MemoryRepository()
    result = ingest_event(
        "trade_closed",
        {
            "strategy_id": "MONDAY_BTCJPY",
            "symbol": "BTCJPY",
            "entry_time": "2026-11-02T02:30:00Z",
            "exit_time": "2026-11-03T05:00:00Z",
            "volume": 0.2,
            "entry_price": 100,
            "exit_price": 101,
            "profit": 1,
            "type": "short",
        },
        repository,
        registry_with_offset,
    )
    assert result["status"] == "processed"
    keys = {alert["rule_key"] for alert in repository.alerts}
    assert {"DIR_VIOLATION", "HOLD_DEVIATION", "ENTRY_OFF_SCHEDULE", "ENTRY_ON_FILTERED_DAY"} <= keys


def test_health_alerts_are_renamed_to_canonical_conformity_rules(registry_with_offset):
    repository = MemoryRepository()
    result = ingest_event(
        "health_alert",
        {"strategy_id": "MONDAY_BTCJPY", "type": "LateExit", "message": "late", "severity": "high"},
        repository,
        registry_with_offset,
    )
    assert result["status"] == "processed"
    assert repository.alerts[0]["rule_key"] == "LATE_EXIT_EVENT"
    assert repository.alerts[0]["severity"] == "high"


@pytest.mark.parametrize(("alert_type", "expected_rule"), [
    ("KillSwitch", "KILL_ACTIVE"),
    ("EAStopped", "EA_STOPPED"),
])
def test_health_alert_names_share_lifecycle_rule_keys(registry_with_offset, alert_type, expected_rule):
    repository = MemoryRepository()
    ingest_event(
        "health_alert",
        {"strategy_id": "MONDAY_BTCJPY", "type": alert_type, "message": "event", "severity": "critical" if alert_type == "KillSwitch" else "medium"},
        repository,
        registry_with_offset,
    )
    assert repository.alerts[0]["rule_key"] == expected_rule


def test_entry_order_rejection_emits_rejects_rule(registry_with_offset):
    repository = MemoryRepository()
    result = ingest_event(
        "order_rejected",
        {
            "strategy_id": "MONDAY_BTCJPY", "context": "EntryBuy", "retcode": 10030,
            "description": "rejected",
        },
        repository,
        registry_with_offset,
    )
    assert result["status"] == "processed"
    assert {alert["rule_key"] for alert in repository.alerts} == {"ORDER_REJECTED", "REJECTS"}


def test_unknown_source_is_saved_for_review_and_opens_high_alert(registry_with_offset):
    repository = MemoryRepository()
    result = ingest_event(
        "heartbeat",
        {"strategy_id": "unknown-ea"},
        repository,
        registry_with_offset,
    )
    ingest_event("heartbeat", {"strategy_id": "unknown-ea"}, repository, registry_with_offset)
    assert result["status"] == "unregistered_source"
    assert repository.raw_events[0]["payload"] == {"strategy_id": "unknown-ea"}
    assert repository.raw_events[0]["ingest_status"] == "rejected"
    assert repository.alerts[0]["rule_key"] == "UNREGISTERED_SOURCE"
    assert repository.alerts[0]["severity"] == "high"
    assert repository.alerts[0]["count"] == 2
    assert len(repository.unregistered_sources) == 1
    assert next(iter(repository.unregistered_sources.values()))["occurrences"] == 2


def test_equity_is_sampled_once_per_minute_and_cashflow_jump_is_flagged(registry_with_offset):
    repository = MemoryRepository()
    first = {"strategy_id": "MONDAY_BTCJPY", "equity": 10000, "ts": "2026-11-18T10:00:02Z"}
    second = {"strategy_id": "MONDAY_BTCJPY", "equity": 10100, "ts": "2026-11-18T10:01:10Z"}
    third = {"strategy_id": "MONDAY_BTCJPY", "equity": 10110, "ts": "2026-11-18T10:01:55Z"}
    fourth = {"strategy_id": "MONDAY_BTCJPY", "equity": 10300, "ts": "2026-11-18T10:02:10Z"}
    ingest_event("equity", first, repository, registry_with_offset)
    ingest_event("equity", second, repository, registry_with_offset)
    ingest_event("equity", third, repository, registry_with_offset)
    ingest_event("equity", fourth, repository, registry_with_offset)

    assert len(repository.equities) == 3
    latest = repository.equities[("MONDAY_BTCJPY", "2026-11-18T08:01:00+00:00")]
    assert latest["equity"] == 10110
    assert latest["cashflow_suspected"] is True
    assert [alert["rule_key"] for alert in repository.alerts] == ["CASHFLOW_SUSPECTED"]
    assert repository.alerts[0]["count"] == 2
    assert len(repository.raw_events) == 4


def test_equity_jump_with_a_closed_trade_in_window_is_not_cashflow(registry_with_offset):
    repository = MemoryRepository()
    ingest_event("equity", {"strategy_id": "MONDAY_BTCJPY", "equity": 10000, "ts": "2026-11-18T10:00:00Z"}, repository, registry_with_offset)
    repository.trades.append({
        "strategy_id": "MONDAY_BTCJPY",
        "exit_time": "2026-11-18T08:00:30+00:00",
    })
    ingest_event("equity", {"strategy_id": "MONDAY_BTCJPY", "equity": 10100, "ts": "2026-11-18T10:01:00Z"}, repository, registry_with_offset)

    latest = repository.equities[("MONDAY_BTCJPY", "2026-11-18T08:01:00+00:00")]
    assert latest["cashflow_suspected"] is False
    assert repository.alerts == []


def test_unverified_offset_keeps_raw_event_pending_without_processing():
    repository = MemoryRepository()
    registry = load_registry()
    result = ingest_event(
        "equity",
        {"strategy_id": "MONDAY_BTCJPY", "equity": 10000, "ts": "2026-11-18T10:00:00Z"},
        repository,
        registry,
    )
    assert result["status"] == "pending_offset"
    assert repository.raw_events[0]["ingest_status"] == "received"
    assert repository.raw_events[0]["ts"] is None
    assert repository.equities == {}


def test_pending_raw_event_can_be_retried_after_offset_is_verified(registry_with_offset):
    repository = MemoryRepository()
    registry_without_offset = load_registry()
    payload = {"strategy_id": "MONDAY_BTCJPY", "equity": 10000, "ts": "2026-11-18T10:00:00Z"}
    first = ingest_event("equity", payload, repository, registry_without_offset)
    second = ingest_event("equity", payload, repository, registry_with_offset)

    assert first["status"] == "pending_offset"
    assert second["status"] == "processed"
    assert len(repository.raw_events) == 1
    assert repository.raw_events[0]["ingest_status"] == "processed"
    assert len(repository.equities) == 1


def test_invalid_event_is_retained_as_rejected_raw_payload(registry_with_offset):
    repository = MemoryRepository()
    with pytest.raises(EventValidationError):
        ingest_event(
            "trade_closed",
            {"strategy_id": "MONDAY_BTCJPY", "entry_time": "not-a-date"},
            repository,
            registry_with_offset,
        )
    assert repository.raw_events[0]["ingest_status"] == "rejected"
    assert repository.raw_events[0]["payload"]["entry_time"] == "not-a-date"


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("strategy_started", {"strategy_id": "MONDAY_BTCJPY", "name": "ALPHACA_MONDAY_BTCJPY", "instrument": "BTCJPY", "timeframe": "H1"}),
        ("capital", {"strategy_id": "MONDAY_BTCJPY", "capital": 10000, "currency": "USD"}),
        ("equity", {"strategy_id": "MONDAY_BTCJPY", "equity": 10000, "ts": "2026-11-18T10:00:00Z"}),
        ("bar_update", {"strategy_id": "MONDAY_BTCJPY", "bars_total": 100, "ts": "2026-11-18T10:00:00Z"}),
        ("trade_closed", {"strategy_id": "MONDAY_BTCJPY", "symbol": "BTCJPY", "entry_time": "2026-11-18T10:00:00Z", "exit_time": "2026-11-18T10:10:00Z", "volume": 0.1, "entry_price": 100, "exit_price": 101, "profit": 10, "type": "long"}),
        ("health_alert", {"strategy_id": "MONDAY_BTCJPY", "type": "LateEntry", "message": "late", "severity": "medium"}),
        ("order_rejected", {"strategy_id": "MONDAY_BTCJPY", "context": "EntryBuy", "retcode": 10030, "description": "rejected"}),
        ("heartbeat", {"strategy_id": "MONDAY_BTCJPY"}),
        ("alert", {"strategy_id": "MONDAY_BTCJPY", "text": "EA started"}),
    ],
)
def test_all_contract_event_types_validate_and_are_retained(event_type, payload, registry_with_offset):
    repository = MemoryRepository()
    result = ingest_event(event_type, payload, repository, registry_with_offset)
    assert result["status"] == "processed"
    assert repository.raw_events[0]["ingest_status"] == "processed"
