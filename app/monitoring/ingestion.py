"""Validated, idempotent ingestion for the normalized monitoring event stream."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from .conformity import evaluate_closed_trade
from .strategies import Portfolio, Strategy, StrategyRegistry

UTC = timezone.utc


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategy_id: str


class StrategyStartedEvent(EventPayload):
    strategy_name: str = Field(validation_alias=AliasChoices("strategy_name", "name"))
    symbol: str = Field(validation_alias=AliasChoices("symbol", "instrument"))
    timeframe: str
    mode: str | None = Field(default=None, validation_alias=AliasChoices("mode", "data_type"))
    param: int | None = Field(default=None, validation_alias=AliasChoices("param", "sizing"))
    start_date: datetime | None = None


class CapitalEvent(EventPayload):
    equity: float = Field(validation_alias=AliasChoices("equity", "capital"))
    currency: str = "USD"


class EquityEvent(EventPayload):
    equity: float = Field(gt=0)
    ts: datetime = Field(validation_alias=AliasChoices("ts", "timestamp"))


class BarUpdateEvent(EventPayload):
    bars_total: int
    ts: datetime | None = Field(default=None, validation_alias=AliasChoices("ts", "timestamp"))


class TradeClosedEvent(EventPayload):
    ticket: str | int | None = None
    symbol: str = Field(validation_alias=AliasChoices("symbol", "instrument"))
    entry_time: datetime
    exit_time: datetime
    volume: float = Field(gt=0, validation_alias=AliasChoices("volume", "quantity"))
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    profit: float = Field(validation_alias=AliasChoices("profit", "pnl"))
    commission: float | None = Field(default=None, validation_alias=AliasChoices("commission", "cost"))
    trade_type: Literal["long", "short"] = Field(validation_alias=AliasChoices("type", "direction", "trade_type"))
    equity_at_open: float | None = None

    @field_validator("trade_type", mode="before")
    @classmethod
    def normalize_trade_type(cls, value):
        return str(value).lower()

    @field_validator("exit_time")
    @classmethod
    def exit_must_follow_entry(cls, value, info):
        entry_time = info.data.get("entry_time")
        if entry_time and value <= entry_time:
            raise ValueError("exit_time must be after entry_time")
        return value


class HealthAlertEvent(EventPayload):
    alert_type: str = Field(validation_alias=AliasChoices("type", "problem_type", "alert_type"))
    message: str = Field(validation_alias=AliasChoices("message", "details"))
    severity: Literal["critical", "high", "medium"]
    timestamp: datetime | None = None


class OrderRejectedEvent(EventPayload):
    context: str
    retcode: int = Field(validation_alias=AliasChoices("retcode", "error_code"))
    description: str = Field(validation_alias=AliasChoices("description", "comment"))
    ts: datetime | None = Field(default=None, validation_alias=AliasChoices("ts", "timestamp"))


class HeartbeatEvent(EventPayload):
    ts: datetime | None = Field(default=None, validation_alias=AliasChoices("ts", "timestamp"))


class FreeAlertEvent(EventPayload):
    text: str = Field(validation_alias=AliasChoices("text", "message", "alert"))
    ts: str | datetime | None = Field(default=None, validation_alias=AliasChoices("ts", "timestamp"))


EVENT_MODELS: dict[str, type[EventPayload]] = {
    "strategy_started": StrategyStartedEvent,
    "capital": CapitalEvent,
    "equity": EquityEvent,
    "bar_update": BarUpdateEvent,
    "trade_closed": TradeClosedEvent,
    "health_alert": HealthAlertEvent,
    "order_rejected": OrderRejectedEvent,
    "heartbeat": HeartbeatEvent,
    "alert": FreeAlertEvent,
}


class EventValidationError(ValueError):
    """An event failed its per-type schema after the raw payload was persisted."""


class IngestionRepository(Protocol):
    def insert_event_raw(self, record: dict[str, Any]) -> tuple[bool, int | str | None, str | None]: ...
    def set_event_status(self, raw_id: int | str | None, status: str, ts: datetime | None = None) -> None: ...
    def find_strategy_alias(self, external_id: str) -> str | None: ...
    def upsert_unregistered_source(self, record: dict[str, Any]) -> None: ...
    def insert_alert(self, record: dict[str, Any]) -> None: ...
    def find_equity_sample(self, strategy_id: str, ts: datetime) -> dict[str, Any] | None: ...
    def find_previous_equity(self, strategy_id: str, ts: datetime) -> dict[str, Any] | None: ...
    def has_closed_trade_between(self, strategy_id: str, start: datetime, end: datetime) -> bool: ...
    def has_open_position(self, strategy_id: str, ts: datetime) -> bool: ...
    def upsert_equity_sample(self, record: dict[str, Any]) -> None: ...
    def upsert_trade(self, record: dict[str, Any]) -> None: ...
    def overlapping_trades(self, strategy_id: str, entry_time: datetime, exit_time: datetime) -> list[dict[str, Any]]: ...
    def recent_order_rejections(self, strategy_id: str, since: datetime) -> list[dict[str, Any]]: ...
    def insert_heartbeat(self, record: dict[str, Any]) -> None: ...


class SupabaseMonitoringRepository:
    """Adapter for the monitoring tables created by migration 0001."""

    def __init__(self, client):
        if client is None:
            raise RuntimeError("Supabase client is not configured")
        self.client = client

    def sync_registry(self, registry: StrategyRegistry) -> bool:
        portfolios = []
        for portfolio in registry.portfolios:
            data = portfolio.model_dump(mode="json")
            data["config"] = data.copy()
            portfolios.append(data)
        if portfolios:
            response = self.client.table("portfolio").upsert(portfolios, on_conflict="id").execute()
            if not isinstance(getattr(response, "data", None), list):
                raise RuntimeError("portfolio registry sync returned an invalid response")

        strategies = []
        for strategy in registry.strategies:
            config = strategy.model_dump(mode="json")
            strategies.append({
                "id": strategy.id,
                "portfolio_id": strategy.portfolio_id,
                "strategy_name_prefix": strategy.strategy_name_prefix,
                "magic": strategy.magic,
                "timeframe": strategy.timeframe,
                "vehicle": strategy.vehicle,
                "direction": strategy.direction,
                "config": config,
            })
        if strategies:
            response = self.client.table("strategy").upsert(strategies, on_conflict="id").execute()
            if not isinstance(getattr(response, "data", None), list):
                raise RuntimeError("strategy registry sync returned an invalid response")
        return True

    def insert_event_raw(self, record: dict[str, Any]) -> tuple[bool, int | str | None, str | None]:
        key = record.get("idempotency_key")
        if key:
            existing = (
                self.client.table("event_raw")
                .select("id,ingest_status")
                .eq("idempotency_key", key)
                .limit(1)
                .execute()
            )
            if existing.data:
                row = existing.data[0]
                return False, row.get("id"), row.get("ingest_status")
        query = self.client.table("event_raw").upsert(
            record, on_conflict="idempotency_key", ignore_duplicates=True
        ).select("id")
        data = query.execute().data or []
        if data:
            return True, data[0].get("id"), "received"
        if key:
            existing = (
                self.client.table("event_raw")
                .select("id,ingest_status")
                .eq("idempotency_key", key)
                .limit(1)
                .execute()
            )
            if existing.data:
                row = existing.data[0]
                return False, row.get("id"), row.get("ingest_status")
        return False, None, None

    def set_event_status(self, raw_id: int | str | None, status: str, ts: datetime | None = None) -> None:
        if raw_id is not None:
            values = {"ingest_status": status}
            if ts is not None:
                values["ts"] = _iso(ts)
            self.client.table("event_raw").update(values).eq("id", raw_id).execute()

    def find_strategy_alias(self, external_id: str) -> str | None:
        result = (
            self.client.table("event_raw")
            .select("strategy_id")
            .eq("event_type", "strategy_started")
            .filter("payload->>strategy_id", "eq", external_id)
            .not_.is_("strategy_id", "null")
            .order("received_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0]["strategy_id"] if result.data else None

    def upsert_unregistered_source(self, record: dict[str, Any]) -> None:
        query = self.client.table("unregistered_source").select("id,occurrences")
        for field in ("source_name", "source_magic"):
            value = record.get(field)
            query = query.is_(field, "null") if value is None else query.eq(field, value)
        existing = query.limit(1).execute().data or []
        if existing:
            self.client.table("unregistered_source").update({
                "last_seen": record["last_seen"],
                "occurrences": existing[0]["occurrences"] + 1,
                "sample_payload": record["sample_payload"],
            }).eq("id", existing[0]["id"]).execute()
        else:
            self.client.table("unregistered_source").insert(record).execute()

    def insert_alert(self, record: dict[str, Any]) -> None:
        query = self.client.table("alert").select("id,count").eq("rule_key", record["rule_key"])
        if record.get("strategy_id") is not None:
            query = query.eq("strategy_id", record["strategy_id"])
        elif record.get("portfolio_id") is not None:
            query = query.eq("portfolio_id", record["portfolio_id"])
        else:
            query = query.is_("strategy_id", "null").is_("portfolio_id", "null")
        active = query.in_("status", ["open", "ack"]).limit(1).execute().data or []
        if active:
            self.client.table("alert").update({
                "count": active[0]["count"] + record.get("count", 1),
                "severity": record["severity"],
                "last_seen": record["last_seen"],
                "context": record["context"],
            }).eq("id", active[0]["id"]).execute()
        else:
            self.client.table("alert").insert(record).execute()

    def find_equity_sample(self, strategy_id: str, ts: datetime) -> dict[str, Any] | None:
        result = (
            self.client.table("equity_sample")
            .select("*")
            .eq("strategy_id", strategy_id)
            .eq("ts", _iso(ts))
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def find_previous_equity(self, strategy_id: str, ts: datetime) -> dict[str, Any] | None:
        result = (
            self.client.table("equity_sample")
            .select("*")
            .eq("strategy_id", strategy_id)
            .lt("ts", _iso(ts))
            .order("ts", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def has_closed_trade_between(self, strategy_id: str, start: datetime, end: datetime) -> bool:
        result = (
            self.client.table("trade")
            .select("id")
            .eq("strategy_id", strategy_id)
            .gte("exit_time", _iso(start))
            .lte("exit_time", _iso(end))
            .limit(1)
            .execute()
        )
        return bool(result.data)

    def has_open_position(self, strategy_id: str, ts: datetime) -> bool:
        # The current EA contract sends no open-position snapshots; avoid inventing one.
        return False

    def upsert_equity_sample(self, record: dict[str, Any]) -> None:
        self.client.table("equity_sample").upsert(
            record, on_conflict="strategy_id,ts"
        ).execute()

    def upsert_trade(self, record: dict[str, Any]) -> None:
        self.client.table("trade").upsert(
            record, on_conflict="strategy_id,ticket,exit_time", ignore_duplicates=True
        ).execute()

    def overlapping_trades(self, strategy_id: str, entry_time: datetime, exit_time: datetime) -> list[dict[str, Any]]:
        response = (
            self.client.table("trade").select("entry_time,exit_time")
            .eq("strategy_id", strategy_id)
            .lt("entry_time", _iso(exit_time))
            .gt("exit_time", _iso(entry_time))
            .execute()
        )
        return response.data or []

    def recent_order_rejections(self, strategy_id: str, since: datetime) -> list[dict[str, Any]]:
        response = (
            self.client.table("event_raw").select("payload,received_at")
            .eq("strategy_id", strategy_id).eq("event_type", "order_rejected")
            .gte("received_at", _iso(since)).execute()
        )
        return response.data or []

    def insert_heartbeat(self, record: dict[str, Any]) -> None:
        self.client.table("heartbeat").insert(record).execute()


def _parse_wall_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    # The broker's configured offset is authoritative; treat the supplied wall clock
    # as server-local even when the reporter appended a literal Z.
    return parsed.replace(tzinfo=None)


def server_time_to_utc(value: str | datetime, offset_hours: float) -> datetime:
    wall_time = _parse_wall_time(value)
    return (wall_time - timedelta(hours=offset_hours)).replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _source_metadata(payload: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    external_id = payload.get("strategy_id")
    source_name = payload.get("strategy_name") or payload.get("name") or payload.get("source_name")
    raw_magic = payload.get("magic")
    if raw_magic is None:
        raw_magic = payload.get("magic_number")
    try:
        magic = int(raw_magic) if raw_magic is not None else None
    except (TypeError, ValueError):
        magic = None
    return (str(source_name) if source_name else None, magic, str(external_id) if external_id else None)


def _resolve_strategy(
    payload: dict[str, Any], registry: StrategyRegistry, repository: IngestionRepository
) -> Strategy | None:
    source_name, magic, external_id = _source_metadata(payload)
    if external_id:
        direct = next((item for item in registry.strategies if item.id == external_id), None)
        if direct:
            return direct
    if source_name:
        matched = registry.match_strategy(source_name)
        if matched:
            return matched
    if magic is not None:
        matches = [item for item in registry.strategies if item.magic == magic]
        if len(matches) == 1:
            return matches[0]
    if external_id:
        canonical_id = repository.find_strategy_alias(external_id)
        if canonical_id:
            return next((item for item in registry.strategies if item.id == canonical_id), None)
    return None


def _idempotency_key(event_type: str, payload: dict[str, Any], provided: str | None) -> str | None:
    if provided or payload.get("idempotency_key") or payload.get("event_id"):
        return str(provided or payload.get("idempotency_key") or payload.get("event_id"))
    external_id = payload.get("strategy_id")
    if event_type == "trade_closed":
        identity = {
            "strategy_id": external_id,
            "ticket": payload.get("ticket"),
            "entry_time": payload.get("entry_time"),
            "exit_time": payload.get("exit_time"),
            "symbol": payload.get("symbol", payload.get("instrument")),
            "volume": payload.get("volume", payload.get("quantity")),
            "entry_price": payload.get("entry_price"),
            "exit_price": payload.get("exit_price"),
            "profit": payload.get("profit", payload.get("pnl")),
        }
    elif event_type in {"equity", "heartbeat", "bar_update", "health_alert", "order_rejected"}:
        ts = payload.get("ts", payload.get("timestamp"))
        if ts is None:
            return None
        identity = {"strategy_id": external_id, "ts": ts, "type": event_type}
        if event_type == "bar_update":
            identity["bars_total"] = payload.get("bars_total")
        elif event_type == "health_alert":
            identity["alert_type"] = payload.get("type", payload.get("problem_type"))
            identity["message"] = payload.get("message", payload.get("details"))
        elif event_type == "order_rejected":
            identity["context"] = payload.get("context")
            identity["retcode"] = payload.get("retcode", payload.get("error_code"))
    else:
        return None
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{event_type}:{hashlib.sha256(encoded).hexdigest()}"


def _event_timestamps(event_type: str, payload: dict[str, Any], parsed: EventPayload) -> dict[str, datetime]:
    if event_type == "trade_closed":
        event = parsed
        return {"entry_time": event.entry_time, "exit_time": event.exit_time}  # type: ignore[attr-defined]
    if event_type == "strategy_started":
        timestamp = parsed.start_date  # type: ignore[attr-defined]
    elif event_type == "health_alert":
        timestamp = parsed.timestamp  # type: ignore[attr-defined]
    else:
        timestamp = getattr(parsed, "ts", None)
    if timestamp is None:
        return {}
    return {"ts": timestamp}


def _expected_hold_minutes(strategy: Strategy) -> float | None:
    exit_rule = strategy.exit
    for field_name, multiplier in (
        ("expected_duration_minutes", 1),
        ("expected_duration_hours", 60),
        ("expected_duration_days", 1440),
    ):
        value = getattr(exit_rule, field_name, None)
        if value is not None:
            return float(value) * multiplier
    return None


def ingest_event(
    event_type: str,
    payload: dict[str, Any],
    repository: IngestionRepository,
    registry: StrategyRegistry,
    *,
    idempotency_key: str | None = None,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist raw first, then validate, normalize, and derive canonical records."""
    if not isinstance(payload, dict):
        payload = {"unparsed_payload": payload}
    if received_at is None:
        received_at = datetime.now(UTC)
    elif received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    else:
        received_at = received_at.astimezone(UTC)
    event_type = str(event_type)
    source_name, source_magic, external_id = _source_metadata(payload)
    strategy = _resolve_strategy(payload, registry, repository)
    key = _idempotency_key(event_type, payload, idempotency_key)

    raw_record = {
        "idempotency_key": key,
        "strategy_id": strategy.id if strategy else None,
        "source_name": source_name or external_id,
        "source_magic": source_magic,
        "event_type": event_type,
        "ts": None,
        "received_at": _iso(received_at),
        "payload": payload,
        "ingest_status": "received",
    }
    inserted, raw_id, existing_status = repository.insert_event_raw(raw_record)
    if not inserted and existing_status != "received":
        return {"status": "duplicate", "strategy_id": strategy.id if strategy else None}
    if not inserted and raw_id is None:
        return {"status": "duplicate", "strategy_id": strategy.id if strategy else None}

    model = EVENT_MODELS.get(event_type)
    if model is None:
        repository.set_event_status(raw_id, "rejected")
        raise EventValidationError(f"unknown event_type: {event_type}")
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        repository.set_event_status(raw_id, "rejected")
        raise EventValidationError(exc.json(include_url=False)) from exc

    if strategy is None:
        source_context = {
            "source_name": source_name or external_id,
            "source_magic": source_magic,
            "external_strategy_id": external_id,
        }
        repository.upsert_unregistered_source({
            **source_context,
            "first_seen": _iso(received_at),
            "last_seen": _iso(received_at),
            "occurrences": 1,
            "sample_payload": payload,
        })
        repository.insert_alert({
            "rule_key": "UNREGISTERED_SOURCE",
            "strategy_id": None,
            "portfolio_id": None,
            "severity": "high",
            "status": "open",
            "first_seen": _iso(received_at),
            "last_seen": _iso(received_at),
            "count": 1,
            "context": source_context,
        })
        repository.set_event_status(raw_id, "rejected")
        return {"status": "unregistered_source", "strategy_id": None}

    portfolio = next(item for item in registry.portfolios if item.id == strategy.portfolio_id)
    timestamps = _event_timestamps(event_type, payload, parsed)
    if timestamps and not portfolio.server_time_to_utc_enabled:
        return {
            "status": "pending_offset",
            "strategy_id": strategy.id,
            "reason": "verified_server_utc_offset_required",
        }

    normalized = {field: server_time_to_utc(value, portfolio.server_utc_offset_hours) for field, value in timestamps.items()}
    source_event_ts = normalized.get("ts") or normalized.get("exit_time")
    event_ts = source_event_ts or received_at

    if event_type == "trade_closed":
        event: TradeClosedEvent = parsed  # type: ignore[assignment]
        entry_time = normalized["entry_time"]
        exit_time = normalized["exit_time"]
        hold_minutes = (exit_time - entry_time).total_seconds() / 60
        expected_hold = _expected_hold_minutes(strategy)
        equity = event.equity_at_open
        if equity is None:
            prior_equity = repository.find_previous_equity(strategy.id, entry_time)
            equity = float(prior_equity["equity"]) if prior_equity else None
        deviation = hold_minutes - expected_hold if expected_hold is not None else None
        trade_record = {
            "strategy_id": strategy.id,
            "ticket": str(event.ticket) if event.ticket is not None else None,
            "symbol": event.symbol,
            "entry_time": _iso(entry_time),
            "exit_time": _iso(exit_time),
            "volume": event.volume,
            "entry_price": event.entry_price,
            "exit_price": event.exit_price,
            "profit": event.profit,
            "commission": event.commission,
            "trade_type": event.trade_type,
            "hold_minutes": hold_minutes,
            "pnl_pct_equity": (event.profit / equity * 100) if equity and equity > 0 else None,
            "duration_deviation_minutes": deviation,
            "cashflow_suspected": False,
        }
        overlapping = repository.overlapping_trades(strategy.id, entry_time, exit_time)
        for signal in evaluate_closed_trade(
            strategy,
            trade_record,
            equity_at_open=float(equity) if equity and equity > 0 else None,
            overlapping_trades=overlapping,
            server_offset_hours=portfolio.server_utc_offset_hours if portfolio.server_time_to_utc_enabled else None,
        ):
            repository.insert_alert({
                "rule_key": signal["rule_key"],
                "strategy_id": strategy.id,
                "portfolio_id": None,
                "severity": signal["severity"],
                "status": "open",
                "first_seen": _iso(exit_time),
                "last_seen": _iso(exit_time),
                "count": 1,
                "context": {**signal["context"], "ticket": trade_record["ticket"]},
            })
        repository.upsert_trade(trade_record)
    elif event_type == "equity":
        event: EquityEvent = parsed  # type: ignore[assignment]
        sample_ts = normalized["ts"].replace(second=0, microsecond=0)
        existing_this_minute = repository.find_equity_sample(strategy.id, sample_ts)
        prior = repository.find_previous_equity(strategy.id, sample_ts)
        already_flagged = bool(existing_this_minute and existing_this_minute.get("cashflow_suspected"))
        cashflow_suspected = already_flagged
        cashflow_newly_suspected = False
        if prior and float(prior["equity"]) > 0:
            delta = abs(event.equity - float(prior["equity"])) / float(prior["equity"])
            trade_since = repository.has_closed_trade_between(
                strategy.id, _parse_repo_time(prior["ts"]), sample_ts
            )
            position_open = repository.has_open_position(strategy.id, sample_ts)
            jump_is_suspected = delta > 0.005 and not trade_since and not position_open
            cashflow_newly_suspected = jump_is_suspected and not already_flagged
            cashflow_suspected = already_flagged or jump_is_suspected
        repository.upsert_equity_sample({
            "strategy_id": strategy.id,
            "ts": _iso(sample_ts),
            "equity": event.equity,
            "currency": payload.get("currency"),
            "cashflow_suspected": cashflow_suspected,
        })
        if cashflow_newly_suspected:
            repository.insert_alert({
                "rule_key": "CASHFLOW_SUSPECTED",
                "strategy_id": strategy.id,
                "portfolio_id": None,
                "severity": "medium",
                "status": "open",
                "first_seen": _iso(sample_ts),
                "last_seen": _iso(sample_ts),
                "count": 1,
                "context": {
                    "previous_equity": float(prior["equity"]),
                    "equity": event.equity,
                    "change_pct": delta * 100,
                },
            })
    elif event_type == "heartbeat":
        repository.insert_heartbeat({
            "strategy_id": strategy.id,
            "ts": _iso(normalized.get("ts", received_at)),
            "received_at": _iso(received_at),
            "payload": payload,
        })
    elif event_type in {"health_alert", "order_rejected"}:
        if event_type == "health_alert":
            event: HealthAlertEvent = parsed  # type: ignore[assignment]
            rule_key = {
                "LATEEXIT": "LATE_EXIT_EVENT",
                "LATEENTRY": "LATE_ENTRY_EVENT",
                "ZEROLOTS": "ZERO_LOTS",
                "TICKDATAINVALID": "TICK_INVALID",
                "NOHISTORY": "NO_HISTORY",
                "CALENDAREXPIRING": "CALENDAR_EXPIRING",
            }.get(event.alert_type.upper().replace(" ", "").replace("_", ""), event.alert_type.upper().replace(" ", "_"))
            severity = event.severity
            context = {"type": event.alert_type, "message": event.message, "payload": payload}
        else:
            event: OrderRejectedEvent = parsed  # type: ignore[assignment]
            rule_key = "ORDER_REJECTED"
            severity = "high"
            context = {
                "context": event.context,
                "retcode": event.retcode,
                "description": event.description,
                "payload": payload,
            }
        repository.insert_alert({
            "rule_key": rule_key,
            "strategy_id": strategy.id,
            "portfolio_id": None,
            "severity": severity,
            "status": "open",
            "first_seen": _iso(event_ts),
            "last_seen": _iso(event_ts),
            "count": 1,
            "context": context,
        })
        if event_type == "order_rejected":
            recent_rejections = repository.recent_order_rejections(strategy.id, received_at - timedelta(hours=24))
            entry_reject = event.context.lower().startswith("entry")
            if entry_reject or len(recent_rejections) >= 3:
                repository.insert_alert({
                    "rule_key": "REJECTS",
                    "strategy_id": strategy.id,
                    "portfolio_id": None,
                    "severity": "high",
                    "status": "open",
                    "first_seen": _iso(event_ts),
                    "last_seen": _iso(event_ts),
                    "count": 1,
                    "context": {
                        "entry_context_rejected": entry_reject,
                        "rejections_last_24h": len(recent_rejections),
                        "last_rejection": context,
                    },
                })

    repository.set_event_status(raw_id, "processed", source_event_ts)
    return {"status": "processed", "strategy_id": strategy.id}


def _parse_repo_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
