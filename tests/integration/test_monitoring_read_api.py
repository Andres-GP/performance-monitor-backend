from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _table(data=None, count=None, *, ack_row=None):
    table = MagicMock()
    query = MagicMock()
    for name in ("eq", "gte", "lte", "in_", "order", "limit", "range"):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=data or [], count=count)
    table.select.return_value = query
    update = MagicMock()
    update.eq.return_value = update
    update.execute.return_value = SimpleNamespace(data=[])
    table.update.return_value = update
    if ack_row is not None:
        query.execute.return_value = SimpleNamespace(data=[ack_row], count=1)
    return table


@pytest.fixture
def monitoring_tables(mock_supabase):
    tables = {
        "daily_stats": _table([]),
        "alert": _table([]),
        "trade": _table([]),
        "equity_sample": _table([]),
        "heartbeat": _table([]),
        "rule_state": _table([]),
        "event_raw": _table([]),
    }
    old_side_effect = mock_supabase.table.side_effect
    mock_supabase.table.side_effect = lambda name: tables.setdefault(name, _table([]))
    yield tables
    mock_supabase.table.side_effect = old_side_effect


def test_portfolio_list_and_detail_use_registered_portfolio_and_metrics(client, auth_header, monitoring_tables):
    monitoring_tables["daily_stats"] = _table([{"equity": 12000, "total_dd_pct": 1.2}])
    monitoring_tables["heartbeat"] = _table([{"ts": "2026-11-19T19:59:00+00:00"}])
    monitoring_tables["equity_sample"] = _table([{
        "strategy_id": "MONDAY_BTCJPY", "ts": "2026-11-19T19:59:40+00:00", "equity": 12000,
    }, {
        "strategy_id": "WEEKLYMOM_ETHUSD", "ts": "2026-11-19T19:59:20+00:00", "equity": 8000,
    }])
    response = client.get("/portfolios?limit=1&offset=0", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2 and len(data["items"]) == 1
    assert data["items"][0]["id"] == "P_AXI"

    response = client.get("/portfolios/P_AXI", headers=auth_header)
    assert response.status_code == 200
    assert response.json()["portfolio"]["id"] == "P_AXI"
    assert response.json()["metrics"]["equity"] == 12000
    assert len(response.json()["strategies"]) == 3
    assert response.json()["strategies"][0]["last_heartbeat_at"] == "2026-11-19T19:59:00+00:00"
    assert response.json()["equity_curve"][0]["equity"] == 20000


def test_strategy_detail_and_paginated_date_filtered_trades(client, auth_header, monitoring_tables):
    monitoring_tables["daily_stats"] = _table([{"trade_count": 17}])
    monitoring_tables["trade"] = _table([{"strategy_id": "MONDAY_BTCJPY", "profit": 5}], count=42)
    detail = client.get("/strategies/MONDAY_BTCJPY", headers=auth_header)
    assert detail.status_code == 200
    assert detail.json()["metrics"]["trade_count"] == 17

    trades = client.get(
        "/strategies/MONDAY_BTCJPY/trades?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:00Z&limit=10&offset=5",
        headers=auth_header,
    )
    assert trades.status_code == 200
    assert trades.json()["limit"] == 10 and trades.json()["offset"] == 5
    assert trades.json()["total"] == 42
    assert len(trades.json()["items"]) == 1


def test_equity_filters_and_rejects_reversed_time_range(client, auth_header, monitoring_tables):
    monitoring_tables["equity_sample"] = _table([{"strategy_id": "MONDAY_BTCJPY", "equity": 10100}], count=1)
    response = client.get(
        "/strategies/MONDAY_BTCJPY/equity?from=2026-11-01T00:00:00Z&to=2026-11-30T23:59:00Z",
        headers=auth_header,
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["equity"] == 10100
    reversed_range = client.get(
        "/strategies/MONDAY_BTCJPY/equity?from=2026-12-01T00:00:00Z&to=2026-11-01T00:00:00Z",
        headers=auth_header,
    )
    assert reversed_range.status_code == 422


def test_alert_filters_ack_and_correlation_read(client, auth_header, monitoring_tables):
    monitoring_tables["alert"] = _table([{"id": 13, "rule_key": "HB_STALE", "status": "open"}], count=1, ack_row={"id": 13, "rule_key": "HB_STALE", "status": "open"})
    alerts = client.get("/alerts?status=open&severity=high&limit=5", headers=auth_header)
    assert alerts.status_code == 200 and alerts.json()["items"][0]["rule_key"] == "HB_STALE"

    ack = client.post("/alerts/13/ack", headers=auth_header)
    assert ack.status_code == 200 and ack.json() == {"id": 13, "status": "ack"}
    monitoring_tables["alert"].update.assert_called_once()

    monitoring_tables["rule_state"] = _table([{
        "scope_id": "MONDAY_BTCJPY|WEEKLYMOM_ETHUSD",
        "last_evaluated_at": "2026-11-19T20:00:00+00:00",
        "state": {"strategy_a": "MONDAY_BTCJPY", "strategy_b": "WEEKLYMOM_ETHUSD", "correlation": 0.61, "band": "red"},
    }])
    corr = client.get("/portfolios/P_AXI/correlation", headers=auth_header)
    assert corr.status_code == 200
    assert corr.json()["items"][0]["correlation"] == 0.61


def test_read_api_requires_authentication(client):
    assert client.get("/portfolios").status_code == 403
    assert client.get("/strategies/MONDAY_BTCJPY").status_code == 403


def test_latest_weekly_report_is_authenticated_and_selects_latest(tmp_path, client, auth_header, monkeypatch):
    import app.api

    monkeypatch.setattr(app.api, "WEEKLY_REPORTS_ROOT", tmp_path)
    older = tmp_path / "2026-W46"
    latest = tmp_path / "2026-W47"
    older.mkdir()
    latest.mkdir()
    (older / "summary.json").write_text('{"week":"2026-W46","strategies":[]}')
    (latest / "summary.json").write_text('{"week":"2026-W47","strategies":[{"strategy_id":"S1","ehi":71}]}')

    assert client.get("/weekly/reports/latest").status_code == 403
    response = client.get("/weekly/reports/latest", headers=auth_header)
    assert response.status_code == 200
    assert response.json()["week"] == "2026-W47"
    assert response.json()["strategies"][0]["ehi"] == 71


def test_latest_weekly_report_returns_404_when_missing(tmp_path, client, auth_header, monkeypatch):
    import app.api

    monkeypatch.setattr(app.api, "WEEKLY_REPORTS_ROOT", tmp_path)
    response = client.get("/weekly/reports/latest", headers=auth_header)
    assert response.status_code == 404
