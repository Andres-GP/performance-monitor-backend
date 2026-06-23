# tests/integration/test_websocket.py
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from app.websocket_server import PerformanceWebSocketServer
from app.config import settings

@pytest.fixture
def ws_server():
    return PerformanceWebSocketServer()

@pytest.mark.asyncio
async def test_websocket_auth_success(ws_server):
    websocket_mock = MagicMock()
    # Usamos AsyncMock para métodos que serán await
    websocket_mock.send = AsyncMock()
    websocket_mock.close = AsyncMock()
    # Registrar el websocket en connections
    ws_server.connections[websocket_mock] = {"authenticated": False, "platform": "unknown"}

    await ws_server._handle_message(websocket_mock, json.dumps({
        "type": "auth",
        "token": settings.API_SECRET_KEY,
        "platform": "MT5"
    }))

    # Verificar que se envió auth_ok
    websocket_mock.send.assert_awaited_once()
    call_args = websocket_mock.send.call_args[0][0]
    assert json.loads(call_args)["type"] == "auth_ok"
    assert ws_server.connections[websocket_mock]["authenticated"] is True
    assert ws_server.connections[websocket_mock]["platform"] == "MT5"

@pytest.mark.asyncio
async def test_websocket_auth_failure(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    websocket_mock.close = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": False, "platform": "unknown"}

    await ws_server._handle_message(websocket_mock, json.dumps({
        "type": "auth",
        "token": "invalid_token"
    }))

    websocket_mock.send.assert_awaited_once()
    call_args = websocket_mock.send.call_args[0][0]
    assert json.loads(call_args)["type"] == "auth_error"
    websocket_mock.close.assert_awaited_once()
    assert ws_server.connections[websocket_mock]["authenticated"] is False

@pytest.mark.asyncio
async def test_websocket_unauthenticated_message(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": False, "platform": "unknown"}

    await ws_server._handle_message(websocket_mock, json.dumps({"type": "ping"}))

    websocket_mock.send.assert_awaited_once()
    call_args = websocket_mock.send.call_args[0][0]
    assert json.loads(call_args)["type"] == "error"
    assert "Not authenticated" in json.loads(call_args)["reason"]

@pytest.mark.asyncio
async def test_websocket_strategy_started(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": True, "platform": "MT5"}

    with patch('app.websocket_server.upsert_strategy') as mock_upsert:
        await ws_server._handle_message(websocket_mock, json.dumps({
            "type": "strategy_started",
            "strategy_id": "test_123",
            "name": "TestStrategy",
            "instrument": "EURUSD",
            "start_date": "2026-06-22T10:00:00Z"
        }))

        mock_upsert.assert_called_once()
        websocket_mock.send.assert_awaited_once()
        call_args = websocket_mock.send.call_args[0][0]
        assert json.loads(call_args)["type"] == "strategy_registered"

@pytest.mark.asyncio
async def test_websocket_trade_closed(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": True, "platform": "MT5"}

    with patch('app.websocket_server.insert_trade') as mock_insert:
        await ws_server._handle_message(websocket_mock, json.dumps({
            "type": "trade_closed",
            "strategy_id": "test_123",
            "instrument": "EURUSD",
            "entry_time": "2026-06-22T10:05:00Z",
            "exit_time": "2026-06-22T10:30:00Z",
            "quantity": 1,
            "entry_price": 1.10,
            "exit_price": 1.12,
            "pnl": 20,
            "direction": "Long"
        }))

        mock_insert.assert_called_once()
        websocket_mock.send.assert_awaited_once()
        call_args = websocket_mock.send.call_args[0][0]
        assert json.loads(call_args)["type"] == "trade_recorded"

@pytest.mark.asyncio
async def test_websocket_ping(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": True, "platform": "MT5"}

    await ws_server._handle_message(websocket_mock, json.dumps({"type": "ping"}))

    websocket_mock.send.assert_awaited_once()
    call_args = websocket_mock.send.call_args[0][0]
    assert json.loads(call_args)["type"] == "pong"

@pytest.mark.asyncio
async def test_websocket_invalid_json(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": True, "platform": "MT5"}

    await ws_server._handle_message(websocket_mock, "not a json")

    websocket_mock.send.assert_awaited_once()
    call_args = websocket_mock.send.call_args[0][0]
    assert json.loads(call_args)["type"] == "error"
    assert "Invalid JSON" in json.loads(call_args)["reason"]

@pytest.mark.asyncio
async def test_websocket_unknown_message(ws_server):
    websocket_mock = MagicMock()
    websocket_mock.send = AsyncMock()
    ws_server.connections[websocket_mock] = {"authenticated": True, "platform": "MT5"}

    await ws_server._handle_message(websocket_mock, json.dumps({"type": "unknown"}))

    # No debería enviar nada porque es un mensaje desconocido (solo log)
    websocket_mock.send.assert_not_called()