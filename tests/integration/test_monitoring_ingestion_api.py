def test_monitor_event_ingestion_route_requires_authentication(client):
    response = client.post("/monitor/events", json={"event_type": "heartbeat", "payload": {"strategy_id": "MONDAY_BTCJPY"}})
    assert response.status_code == 403


def test_monitor_event_ingestion_route_dispatches_valid_envelope(client, auth_header, mocker):
    mocker.patch(
        "app.api.ingest_event",
        return_value={"status": "processed", "strategy_id": "MONDAY_BTCJPY"},
    )
    response = client.post(
        "/monitor/events",
        json={"event_type": "heartbeat", "payload": {"strategy_id": "MONDAY_BTCJPY"}},
        headers=auth_header,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "processed", "strategy_id": "MONDAY_BTCJPY"}


def test_monitor_event_ingestion_route_rejects_malformed_event_after_dispatch(client, auth_header, mocker):
    from app.monitoring.ingestion import EventValidationError

    mocker.patch("app.api.ingest_event", side_effect=EventValidationError("unknown event_type: strange"))
    response = client.post(
        "/monitor/events",
        json={"event_type": "strange", "payload": {"strategy_id": "MONDAY_BTCJPY"}},
        headers=auth_header,
    )
    assert response.status_code == 422
