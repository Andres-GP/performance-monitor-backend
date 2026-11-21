#!/usr/bin/env python3
"""Replay deterministic monitoring events against a non-production API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests


STRATEGIES = {
    "MONDAY_BTCJPY": ("ALPHACA_MONDAY_SIM", "BTCJPY", "H1"),
    "GOTOBI_USDJPY_AXI": ("ALPHACA_GOTOBI_SIM", "USDJPY", "M5"),
    "WEEKLYMOM_ETHUSD": ("ALPHACA_WEEKLYMOM_SIM", "ETHUSD", "H1"),
    "GOTOBI_USDJPY_DWX": ("ALPHACA_GOTOBI_DWX_SIM", "USDJPY", "M5"),
    "RSI2_QQQ": ("TIS_RSI2_SIM", "QQQ", "D1"),
}
SCENARIOS = (
    "normal", "kill-switch", "ea-down", "late-entry", "short-trade",
    "hold-out-of-tolerance", "deposit", "duplicate", "unknown-source",
)


def _event(scenario: str, index: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "payload": payload,
        "idempotency_key": f"replay:{scenario}:{index}",
    }


def scenario_events(scenario: str) -> list[dict[str, Any]]:
    """Create the same synthetic envelopes for CLI replay and HTTP E2E tests."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    events: list[dict[str, Any]] = []
    if scenario == "normal":
        for strategy_id, (name, symbol, timeframe) in STRATEGIES.items():
            events.append(_event(scenario, len(events), "strategy_started", {
                "strategy_id": strategy_id, "strategy_name": name, "symbol": symbol,
                "timeframe": timeframe, "mode": "demo",
            }))
            events.append(_event(scenario, len(events), "capital", {
                "strategy_id": strategy_id, "equity": 10000, "currency": "USD",
            }))
            events.append(_event(scenario, len(events), "heartbeat", {"strategy_id": strategy_id}))
        return events

    target = "MONDAY_BTCJPY"
    if scenario == "kill-switch":
        events.append(_event(scenario, 0, "health_alert", {
            "strategy_id": target, "type": "KillSwitch", "message": "synthetic replay",
            "severity": "critical",
        }))
    elif scenario == "ea-down":
        events.append(_event(scenario, 0, "health_alert", {
            "strategy_id": target, "type": "EAStopped", "message": "synthetic replay",
            "severity": "high",
        }))
    elif scenario == "late-entry":
        events.append(_event(scenario, 0, "health_alert", {
            "strategy_id": target, "type": "LateEntry", "message": "synthetic replay",
            "severity": "medium",
        }))
    elif scenario in {"short-trade", "hold-out-of-tolerance", "duplicate"}:
        direction = "short" if scenario in {"short-trade", "duplicate"} else "long"
        duration_minutes = 60 if scenario == "hold-out-of-tolerance" else 1440
        entry = datetime(2026, 11, 9, tzinfo=timezone.utc)
        exit_ = entry + timedelta(minutes=duration_minutes)
        trade = {
            "strategy_id": target, "ticket": f"REPLAY-{scenario}", "symbol": "BTCJPY",
            "entry_time": entry.isoformat().replace("+00:00", "Z"),
            "exit_time": exit_.isoformat().replace("+00:00", "Z"),
            "volume": 0.01, "entry_price": 100000, "exit_price": 100100,
            "profit": 10, "commission": 0, "type": direction,
        }
        first = _event(scenario, 0, "trade_closed", trade)
        events.append(first)
        if scenario == "duplicate":
            events.append(dict(first))
    elif scenario == "deposit":
        events.extend([
            _event(scenario, 0, "position_snapshot", {
                "strategy_id": target,
                "timestamp": "2026-11-09T09:59:00Z",
                "equity": 10000,
                "margin_used": 0,
                "free_margin": 10000,
                "positions": [],
            }),
            _event(scenario, 1, "equity", {"strategy_id": target, "equity": 10000, "ts": "2026-11-09T10:00:00Z"}),
            _event(scenario, 2, "equity", {"strategy_id": target, "equity": 10100, "ts": "2026-11-09T10:01:00Z"}),
        ])
    elif scenario == "unknown-source":
        events.append(_event(scenario, 0, "heartbeat", {"strategy_id": "UNKNOWN_REPLAY_EA"}))
    return events


def send_events(post, base_url: str, token: str, scenario: str) -> list[dict[str, Any]]:
    results = []
    for envelope in scenario_events(scenario):
        response = post(
            f"{base_url.rstrip('/')}/monitor/events",
            json=envelope,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"body": response.text}
        results.append({"http_status": response.status_code, "result": body, "event": envelope["event_type"]})
        if response.status_code >= 400:
            raise RuntimeError(json.dumps(results[-1], ensure_ascii=False))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("MONITOR_API_URL"), required=not os.getenv("MONITOR_API_URL"))
    parser.add_argument("--token", default=os.getenv("MONITOR_API_TOKEN") or os.getenv("API_SECRET_KEY"))
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument("--confirm-non-production", action="store_true", help="required acknowledgement before sending synthetic events")
    args = parser.parse_args(argv)
    host = (urlparse(args.base_url).hostname or "").lower()
    if not args.confirm_non_production:
        parser.error("pass --confirm-non-production only when the API is a disposable/test environment")
    if host in {"api.alphacacapital.com", "api.alphaca.com"}:
        parser.error("refusing to replay synthetic events to a production hostname")
    if not args.token:
        parser.error("set MONITOR_API_TOKEN or API_SECRET_KEY")
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    try:
        for scenario in scenarios:
            results = send_events(requests.post, args.base_url, args.token, scenario)
            print(json.dumps({"scenario": scenario, "results": results}, ensure_ascii=False))
    except (requests.RequestException, RuntimeError) as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
