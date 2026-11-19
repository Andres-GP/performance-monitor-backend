from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.monitoring.strategies import load_registry
from tests.unit.test_monitoring_ingestion import MemoryRepository
from tools.replay import SCENARIOS, scenario_events


class ReplayRepository(MemoryRepository):
    def sync_registry(self, registry):
        return True


def _api_client(monkeypatch):
    registry = load_registry()
    registry = registry.model_copy(update={
        "portfolios": [
            portfolio.model_copy(update={
                "server_utc_offset_hours": 0,
                "server_utc_offset_verified": True,
            })
            for portfolio in registry.portfolios
        ],
    })
    repository = ReplayRepository()
    monkeypatch.setattr(api, "load_registry", lambda: registry)
    monkeypatch.setattr(api, "SupabaseMonitoringRepository", lambda _client: repository)
    return repository, TestClient(api.create_app())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_replay_scenario_over_http_has_expected_alerts(monkeypatch, auth_header, scenario):
    repository, client = _api_client(monkeypatch)
    try:
        responses = [
            client.post("/monitor/events", json=deepcopy(envelope), headers=auth_header)
            for envelope in scenario_events(scenario)
        ]
        assert all(response.status_code == 200 for response in responses)
        keys = {alert["rule_key"] for alert in repository.alerts}

        expected = {
            "normal": set(),
            "kill-switch": {"KILL_ACTIVE"},
            "ea-down": {"EA_STOPPED"},
            "late-entry": {"LATE_ENTRY_EVENT"},
            "short-trade": {"DIR_VIOLATION"},
            "hold-out-of-tolerance": {"HOLD_DEVIATION"},
            "deposit": {"CASHFLOW_SUSPECTED"},
            "duplicate": {"DIR_VIOLATION"},
            "unknown-source": {"UNREGISTERED_SOURCE"},
        }[scenario]
        assert keys == expected

        if scenario == "normal":
            assert len(repository.heartbeats) == 5
            assert len(repository.raw_events) == 15
        if scenario == "duplicate":
            assert len(repository.trades) == 1
            assert responses[-1].json()["status"] == "duplicate"
        if scenario == "unknown-source":
            assert repository.unregistered_sources
    finally:
        client.close()
