# tests/integration/test_api.py (versión corregida)
import pytest
from unittest.mock import MagicMock
from datetime import datetime

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_start_strategy_new(client, auth_header, sample_strategy_data, mocker):
    # Parcheamos supabase en app.api
    mock_supabase = MagicMock()
    # Configuramos el mock para que no exista la estrategia
    # Simulamos: select().eq().eq().eq().execute() -> data=[]
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_execute = MagicMock(return_value=MagicMock(data=[]))
    
    # Encadenamiento: table().select().eq().eq().eq().execute()
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq  # primer eq
    mock_eq.eq.return_value = mock_eq      # segundo eq (devuelve el mismo para encadenar)
    mock_eq.eq.return_value = mock_eq      # tercer eq
    mock_eq.execute.return_value = mock_execute.return_value  # el execute final
    
    # Mock para upsert
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
    
    # Inyectamos el mock en el módulo api
    mocker.patch('app.api.supabase', mock_supabase)
    
    response = client.post("/strategies/start", json=sample_strategy_data, headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "created"
    assert data["strategy_id"] == sample_strategy_data["strategy_id"]

def test_start_strategy_existing(client, auth_header, sample_strategy_data, mocker):
    mock_supabase = MagicMock()
    # Simulamos que la estrategia ya existe
    existing_data = [{"strategy_id": "existing_id", "state": "Stopped"}]
    
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_execute = MagicMock(return_value=MagicMock(data=existing_data))
    
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.eq.return_value = mock_eq
    mock_eq.eq.return_value = mock_eq
    mock_eq.execute.return_value = mock_execute.return_value
    
    # Mock para update
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    mocker.patch('app.api.supabase', mock_supabase)
    
    response = client.post("/strategies/start", json=sample_strategy_data, headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "reactivated"
    assert data["strategy_id"] == "existing_id"

def test_stop_strategy(client, auth_header, mocker):
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch('app.api.supabase', mock_supabase)
    
    strategy_id = "test_strat_123"
    response = client.post("/strategies/stop", json={"strategy_id": strategy_id}, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_trade_closed(client, auth_header, sample_trade_data, mocker):
    mock_supabase = MagicMock()
    # Simular que la estrategia existe
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"strategy_id": "test_strat_123"}])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch('app.api.supabase', mock_supabase)
    
    response = client.post("/trades", json=sample_trade_data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_alert_received(client, auth_header, mocker):
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"name": "TestStrategy"}])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch('app.api.supabase', mock_supabase)
    
    alert_data = {
        "strategy_id": "test_strat_123",
        "timestamp": "2026-06-22T12:00:00Z",
        "problem_type": "Frozen order",
        "details": "Order stuck",
        "severity": "high"
    }
    response = client.post("/alerts", json=alert_data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "alert received"}

def test_get_strategies(client, auth_header, mocker):
    mock_supabase = MagicMock()
    strategies = [
        {"strategy_id": "s1", "name": "Strat1", "state": "Running"},
        {"strategy_id": "s2", "name": "Strat2", "state": "Stopped"}
    ]
    # Mock para el select principal
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=strategies)
    # Mock para las subconsultas (metrics, edge, backtest, trades, alerts) - devolver vacío
    # Hacemos que cualquier otra llamada a select devuelva vacío
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mocker.patch('app.api.supabase', mock_supabase)
    
    response = client.get("/strategies", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["strategy_id"] == "s1"
    assert "metrics" in data[0]


    # tests/integration/test_api.py (añadir al final del archivo)

def test_heartbeat_success(client, auth_header, mock_supabase):
    """Test heartbeat para estrategia existente."""
    strategy_id = "test_strat_123"
    
    # Mock: estrategia existe
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"strategy_id": strategy_id}]
    )
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.post("/heartbeat", json={"strategy_id": strategy_id}, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    
    # Verificar que se llamó a update con last_heartbeat
    mock_supabase.table.return_value.update.assert_called_once()
    call_args = mock_supabase.table.return_value.update.call_args[0][0]
    assert "last_heartbeat" in call_args

def test_heartbeat_unknown_strategy(client, auth_header, mock_supabase):
    """Test heartbeat para estrategia desconocida."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.post("/heartbeat", json={"strategy_id": "unknown"}, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": "strategy not found"}

def test_heartbeat_missing_strategy_id(client, auth_header):
    """Test heartbeat sin strategy_id."""
    response = client.post("/heartbeat", json={}, headers=auth_header)
    assert response.status_code == 400
    assert "strategy_id required" in response.text

def test_report_capital_new(client, auth_header, mock_supabase):
    """Test reporte de capital para cuenta nueva."""
    # Mock: no existe cuenta
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    
    data = {
        "strategy_id": "test_strat_123",
        "account_type": "demo",
        "capital": 100000.0,
        "currency": "USD"
    }
    response = client.post("/capital/report", json=data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "updated"}
    
    # Verificar que se llamó a insert
    mock_supabase.table.return_value.insert.assert_called_once()

def test_report_capital_existing(client, auth_header, mock_supabase):
    """Test reporte de capital para cuenta existente."""
    # Mock: cuenta existe
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(
        data=[{"id": 1, "account_type": "demo"}]
    )
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    data = {
        "strategy_id": "test_strat_123",
        "account_type": "demo",
        "capital": 150000.0,
        "currency": "USD"
    }
    response = client.post("/capital/report", json=data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "updated"}
    
    # Verificar que se llamó a update
    mock_supabase.table.return_value.update.assert_called_once()

def test_report_capital_missing_capital(client, auth_header):
    """Test reporte de capital sin capital."""
    data = {"strategy_id": "test_strat_123", "account_type": "demo"}
    response = client.post("/capital/report", json=data, headers=auth_header)
    assert response.status_code == 400
    assert "Missing capital" in response.text

def test_get_capital_summary(client, auth_header, mock_supabase):
    """Test resumen de capital."""
    accounts = [
        {"account_type": "demo", "capital": 100000, "currency": "USD"},
        {"account_type": "real", "capital": 200000, "currency": "USD"},
        {"account_type": "demo", "capital": 50000, "currency": "USD"}
    ]
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=accounts)
    
    response = client.get("/capital/summary", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 350000
    assert data["by_type"]["demo"]["total"] == 150000
    assert data["by_type"]["real"]["total"] == 200000
    assert len(data["by_type"]["demo"]["accounts"]) == 2

def test_upload_backtest_success(client, auth_header, mock_supabase):
    """Test subir backtest exitosamente."""
    strategy_id = "test_strat_123"
    
    # Mock: estrategia existe
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"strategy_id": strategy_id}]
    )
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    
    data = {
        "strategy_id": strategy_id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "expected_pnl": 15000,
        "expected_sharpe": 1.8,
        "expected_drawdown": 8.0,
        "parameters": {"fast": 10, "slow": 25}
    }
    response = client.post("/backtest/upload", json=data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "uploaded"}

def test_upload_backtest_strategy_not_found(client, auth_header, mock_supabase):
    """Test subir backtest para estrategia inexistente."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    data = {"strategy_id": "unknown", "period_start": "2025-01-01"}
    response = client.post("/backtest/upload", json=data, headers=auth_header)
    assert response.status_code == 404
    assert "Strategy not found" in response.text

def test_get_strategy_metrics(client, auth_header, mock_supabase):
    """Test obtener métricas de una estrategia."""
    strategy_id = "test_strat_123"
    metrics_data = [
        {"strategy_id": strategy_id, "date": "2026-06-22", "win_rate": 60.0, "profit_factor": 1.5}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = MagicMock(data=metrics_data)
    
    response = client.get(f"/performance/metrics/{strategy_id}", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["win_rate"] == 60.0

def test_get_strategy_trades(client, auth_header, mock_supabase):
    """Test obtener trades de una estrategia."""
    strategy_id = "test_strat_123"
    trades_data = [
        {"strategy_id": strategy_id, "instrument": "EURUSD", "pnl": 100},
        {"strategy_id": strategy_id, "instrument": "EURUSD", "pnl": -50}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=trades_data)
    
    response = client.get(f"/strategies/{strategy_id}/trades", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["strategy_id"] == strategy_id

def test_get_strategy_trades_not_found(client, auth_header, mock_supabase):
    """Test obtener trades de estrategia sin trades."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.get("/strategies/unknown/trades", headers=auth_header)
    assert response.status_code == 404
    assert "No trades found" in response.text

def test_get_alerts(client, auth_header, mock_supabase):
    """Test obtener alertas."""
    alerts_data = [
        {"id": 1, "strategy_id": "s1", "problem_type": "Frozen order"},
        {"id": 2, "strategy_id": "s2", "problem_type": "Connection lost"}
    ]
    mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=alerts_data)
    
    response = client.get("/alerts?limit=2", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

def test_get_market_regime(client, auth_header, mock_supabase):
    """Test obtener régimen de mercado."""
    regime_data = [
        {"id": 1, "trend": "trending", "fear": "normal", "volatility": "normal"}
    ]
    mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=regime_data)
    
    response = client.get("/market/regime", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["trend"] == "trending"

def test_get_market_regime_not_found(client, auth_header, mock_supabase):
    """Test obtener régimen de mercado sin datos."""
    mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.get("/market/regime", headers=auth_header)
    assert response.status_code == 404
    assert "No market regime data available" in response.text

def test_delete_strategy_success(client, auth_header, mock_supabase):
    """Test eliminar estrategia en estado Stopped."""
    strategy_id = "test_strat_123"
    
    # Mock: estrategia existe y está Stopped
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"strategy_id": strategy_id, "state": "Stopped"}]
    )
    # Mock para eliminaciones
    mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.delete(f"/strategies/{strategy_id}", headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}

def test_delete_strategy_not_stopped(client, auth_header, mock_supabase):
    """Test eliminar estrategia que no está Stopped."""
    strategy_id = "test_strat_123"
    
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"strategy_id": strategy_id, "state": "Running"}]
    )
    
    response = client.delete(f"/strategies/{strategy_id}", headers=auth_header)
    assert response.status_code == 400
    assert "Strategy must be Stopped before deletion" in response.text

def test_delete_strategy_not_found(client, auth_header, mock_supabase):
    """Test eliminar estrategia inexistente."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.delete("/strategies/unknown", headers=auth_header)
    assert response.status_code == 404
    assert "Strategy not found" in response.text

def test_get_portfolio_metrics(client, auth_header, mock_supabase):
    """Test obtener métricas de portafolio."""
    metrics_data = [
        {"id": 1, "sharpe_ratio": 1.5, "max_drawdown": 5.0}
    ]
    mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=metrics_data)
    
    response = client.get("/portfolio/metrics", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["sharpe_ratio"] == 1.5

def test_get_portfolio_metrics_not_found(client, auth_header, mock_supabase):
    """Test obtener métricas de portafolio sin datos."""
    mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    
    response = client.get("/portfolio/metrics", headers=auth_header)
    assert response.status_code == 404
    assert "No portfolio metrics available" in response.text

def test_set_portfolio_weights(client, auth_header, mock_supabase):
    """Test establecer pesos de portafolio."""
    strategy_id = "test_strat_123"
    
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"strategy_id": strategy_id}]
    )
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
    
    data = {"strategy_id": strategy_id, "target_weight": 40}
    response = client.post("/portfolio/weights", json=data, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {"status": "updated"}

def test_set_portfolio_weights_invalid(client, auth_header):
    """Test establecer pesos sin datos requeridos."""
    response = client.post("/portfolio/weights", json={}, headers=auth_header)
    assert response.status_code == 400
    assert "strategy_id and target_weight required" in response.text

def test_get_portfolio_weights(client, auth_header, mock_supabase):
    """Test obtener pesos de portafolio."""
    weights_data = [
        {"strategy_id": "s1", "target_weight": 40},
        {"strategy_id": "s2", "target_weight": 60}
    ]
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=weights_data)
    
    response = client.get("/portfolio/weights", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["target_weight"] == 40