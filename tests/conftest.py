# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.api import create_app
from app.config import settings
from app.supabase_client import supabase


# --- Mock de Supabase (global) ---
@pytest.fixture(scope="session", autouse=True)
def mock_supabase():
    """
    Reemplaza el cliente de Supabase real por un mock global.
    Se aplica automáticamente a todas las pruebas.
    """
    original_supabase = supabase

    # Creamos un mock con todas las operaciones necesarias
    mock_client = MagicMock()
    
    # Configuración de los métodos de tabla
    mock_client.table = MagicMock()
    mock_client.table.return_value.select = MagicMock()
    mock_client.table.return_value.insert = MagicMock()
    mock_client.table.return_value.update = MagicMock()
    mock_client.table.return_value.delete = MagicMock()
    mock_client.table.return_value.eq = MagicMock()
    mock_client.table.return_value.gte = MagicMock()
    mock_client.table.return_value.order = MagicMock()
    mock_client.table.return_value.limit = MagicMock()
    mock_client.table.return_value.execute = MagicMock()
    
    # Respuestas por defecto (vacías)
    mock_client.table.return_value.execute.return_value = MagicMock(data=[])
    mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
    
    # Configuramos el encadenamiento de eq para que devuelva el mismo mock
    # Esto permite que .eq().eq().eq() funcione sin problemas
    mock_client.table.return_value.eq.return_value = mock_client.table.return_value

    # Inyectar en los módulos que usan supabase
    import app.api
    app.api.supabase = mock_client

    import app.monitor
    app.monitor.supabase = mock_client

    import app.supabase_client
    app.supabase_client.supabase = mock_client

    yield mock_client

    # Restaurar después de los tests
    app.api.supabase = original_supabase
    app.monitor.supabase = original_supabase
    app.supabase_client.supabase = original_supabase


# --- Mock de Resend (para no enviar correos) ---
@pytest.fixture(autouse=True)
def mock_resend():
    """Mock de la función de envío de emails para evitar enviar correos reales."""
    import app.api
    app.api.RESEND_API_KEY = "fake_key"
    app.api.send_alert_email = MagicMock()
    yield


# --- Mock de yfinance (para no hacer llamadas reales) ---
@pytest.fixture(autouse=True)
def mock_yfinance():
    """Mock de las funciones de yfinance para evitar descargas reales de datos."""
    import app.analytics.regime
    app.analytics.regime.get_adx = MagicMock(return_value=25.0)
    app.analytics.regime.get_vix_percentile = MagicMock(return_value=50.0)
    app.analytics.regime.get_atr_percentile = MagicMock(return_value=50.0)
    app.analytics.regime.get_advance_decline_ratio = MagicMock(return_value=1.0)
    app.analytics.regime.get_nh_nl_ratio = MagicMock(return_value=1.0)
    app.analytics.regime.get_correlation = MagicMock(return_value=0.5)
    app.analytics.regime.get_average_daily_volume = MagicMock(return_value=1000000)
    yield


# --- Fixture: Cliente HTTP para pruebas de integración ---
@pytest.fixture
def client(mock_supabase):
    """Crea un cliente de pruebas para la API."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# --- Fixture: Header de autenticación ---
@pytest.fixture
def auth_header():
    """Devuelve el header de autenticación con el token correcto."""
    return {"Authorization": f"Bearer {settings.API_SECRET_KEY}"}


# --- Fixtures: Datos de ejemplo ---
@pytest.fixture
def sample_strategy_data():
    return {
        "strategy_id": "test_strat_123",
        "name": "TestStrategy",
        "instrument": "EURUSD",
        "instrument_type": "Forex",
        "timeframe": "1H",
        "data_type": "Simulation",
        "platform": "MT5",
        "sizing": 10,
        "start_date": "2026-06-22T10:00:00Z",
        "state": "Running"
    }


@pytest.fixture
def sample_trade_data():
    return {
        "strategy_id": "test_strat_123",
        "instrument": "EURUSD",
        "entry_time": "2026-06-22T10:05:00Z",
        "exit_time": "2026-06-22T10:30:00Z",
        "quantity": 1,
        "entry_price": 1.1000,
        "exit_price": 1.1020,
        "pnl": 20.0,
        "direction": "Long",
        "cost": 0.5
    }