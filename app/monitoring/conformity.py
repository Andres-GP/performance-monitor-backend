"""Frozen strategy rule checks for a just-closed trade (Step 7)."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any

from .strategies import Strategy

UTC = timezone.utc


def _first_monday(year: int, month: int) -> int:
    return next(day for day in range(1, 8) if datetime(year, month, day).weekday() == 0)


def _is_gotobi_day(value: datetime, dates: list[int | str] | None) -> bool:
    days = dates or [5, 10, 15, 20, 25, 30, "end_of_month"]
    return value.day in [day for day in days if isinstance(day, int)] or (
        "end_of_month" in days and value.day == calendar.monthrange(value.year, value.month)[1]
    )


def evaluate_closed_trade(
    strategy: Strategy,
    trade: dict[str, Any],
    *,
    equity_at_open: float | None = None,
    overlapping_trades: list[dict[str, Any]] | None = None,
    server_offset_hours: float | None = None,
) -> list[dict[str, Any]]:
    """Return rule signals; unavailable inputs disable only their dependent rule."""
    entry = _dt(trade["entry_time"])
    exit_ = _dt(trade["exit_time"])
    hold_minutes = (exit_ - entry).total_seconds() / 60
    signals: list[dict[str, Any]] = []

    def add(rule_key: str, severity: str, context: dict[str, Any]):
        signals.append({"rule_key": rule_key, "severity": severity, "context": context})

    if trade.get("trade_type") != strategy.direction:
        add("DIR_VIOLATION", "critical", {
            "actual_direction": trade.get("trade_type"), "expected_direction": strategy.direction,
        })

    expected_hold = _expected_hold_minutes(strategy)
    tolerance = strategy.exit.tolerance_minutes
    if expected_hold is not None and tolerance is not None and abs(hold_minutes - expected_hold) > tolerance:
        add("HOLD_DEVIATION", "high", {
            "hold_minutes": hold_minutes, "expected_minutes": expected_hold,
            "tolerance_minutes": tolerance,
        })

    _check_entry_schedule(strategy, entry, add, server_offset_hours)
    _check_size(strategy, trade, equity_at_open, add)
    if overlapping_trades is not None:
        max_open = _max_concurrency(overlapping_trades + [trade])
        if max_open > strategy.max_positions:
            add("CONCURRENCY", "high", {
                "max_overlapping_positions": max_open,
                "allowed_positions": strategy.max_positions,
            })
    return signals


def _check_entry_schedule(strategy, entry, add, server_offset_hours):
    tolerance = strategy.entry_tolerance_minutes
    if tolerance is None:
        return
    schedule_time = strategy.entry.time
    if not schedule_time:
        return
    hour, minute = (int(part) for part in schedule_time.split(":")[:2])
    if strategy.entry.timezone == "broker_server":
        if server_offset_hours is None:
            return
        local_entry = entry + timedelta(hours=server_offset_hours)
        expected_weekday = None if strategy.id.startswith("GOTOBI_") else 0
        target = local_entry.replace(hour=hour, minute=minute, second=0, microsecond=0)
        deviation = abs((local_entry - target).total_seconds()) / 60
        context_entry = local_entry
    else:
        context_entry = entry
        target = entry.replace(hour=hour, minute=minute, second=0, microsecond=0)
        deviation = abs((entry - target).total_seconds()) / 60
        expected_weekday = None if strategy.id.startswith("GOTOBI_") else 0
    if deviation > tolerance or (expected_weekday is not None and context_entry.weekday() != expected_weekday):
        add("ENTRY_OFF_SCHEDULE", "high", {
            "entry_time": entry.isoformat(), "expected_weekday": "Monday" if expected_weekday == 0 else None,
            "expected_time": schedule_time, "tolerance_minutes": tolerance,
            "time_deviation_minutes": deviation,
        })

    if strategy.id == "MONDAY_BTCJPY" and context_entry.weekday() == 0:
        if context_entry.day == _first_monday(context_entry.year, context_entry.month):
            add("ENTRY_ON_FILTERED_DAY", "high", {
                "entry_date": context_entry.date().isoformat(), "filter": "first Monday of month",
            })
    if strategy.id.startswith("GOTOBI_"):
        target_day = context_entry.date() + timedelta(days=1)
        valid_date = _is_gotobi_day(datetime.combine(target_day, datetime.min.time()), strategy.entry.gotobi_dates)
        excluded = set(strategy.entry.excluded_dates or [])
        if not valid_date or target_day.isoformat() in excluded:
            add("ENTRY_ON_FILTERED_DAY", "high", {
                "entry_date": context_entry.date().isoformat(),
                "target_gotobi_date": target_day.isoformat(),
                "excluded_dates": sorted(excluded),
            })


def _check_size(strategy, trade, equity, add):
    if strategy.contract_size is None or equity is None or equity <= 0:
        return
    if strategy.expected_size.kind != "equity_notional_fraction":
        return
    notional_fraction = float(trade["volume"]) * strategy.contract_size * float(trade["entry_price"]) / equity
    expected = strategy.expected_size.value
    deviation_pct = abs(notional_fraction - expected) / expected * 100
    if strategy.id == "WEEKLYMOM_ETHUSD" and notional_fraction >= expected:
        return
    if deviation_pct > 25:
        add("SIZE_DEVIATION", "medium", {
            "actual_notional_fraction": notional_fraction,
            "expected_notional_fraction": expected,
            "deviation_pct": deviation_pct,
            "equity_at_open": equity,
        })


def _expected_hold_minutes(strategy: Strategy) -> float | None:
    for name, multiplier in (("expected_duration_minutes", 1), ("expected_duration_hours", 60), ("expected_duration_days", 1440)):
        value = getattr(strategy.exit, name)
        if value is not None:
            return float(value) * multiplier
    return None


def _max_concurrency(trades: list[dict[str, Any]]) -> int:
    points = []
    for row in trades:
        points.append((_dt(row["entry_time"]), 1))
        points.append((_dt(row["exit_time"]), -1))
    # Exits are processed before entries at equal timestamps; touching trades do not overlap.
    count = maximum = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        count += delta
        maximum = max(maximum, count)
    return maximum


def _dt(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
