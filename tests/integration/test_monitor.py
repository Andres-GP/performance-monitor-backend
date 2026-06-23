import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import numpy as np
from app.monitor import PerformanceMonitor

@pytest.fixture
def monitor(mock_supabase):
    return PerformanceMonitor(mock_supabase)

@pytest.mark.asyncio
async def test_run_daily_check(monitor, mock_supabase):
    mock_supabase.reset_mock()
    strategies_data = [
        {"strategy_id": "s1", "name": "Strat1", "state": "Running"},
        {"strategy_id": "s2", "name": "Strat2", "state": "Running"}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=strategies_data)

    trades_data = [
        {"pnl": 100, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": -50, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": 200, "exit_time": datetime.utcnow().isoformat()}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=trades_data)

    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    with patch('app.monitor.send_alert_email') as mock_email:
        await monitor.run_daily_check()
        mock_email.assert_not_called()
        assert mock_supabase.table.return_value.insert.call_count == 0

@pytest.mark.asyncio
async def test_check_mt5_heartbeats(monitor, mock_supabase):
    mock_supabase.reset_mock()
    now = datetime.utcnow()
    old_time = (now - timedelta(seconds=200)).isoformat()
    strategies_data = [
        {"strategy_id": "mt5_1", "platform": "MT5", "state": "Running", "last_heartbeat": old_time}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=strategies_data)
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    await monitor.check_mt5_heartbeats()

    mock_supabase.table.return_value.update.assert_called_once()
    call_args = mock_supabase.table.return_value.update.call_args[0][0]
    assert call_args["state"] == "Stopped"

@pytest.mark.asyncio
async def test_check_strategy_performance_healthy(monitor, mock_supabase):
    mock_supabase.reset_mock()
    strategy = {"strategy_id": "s1", "name": "Strat1", "state": "Running"}
    trades_data = [
        {"pnl": 100, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": 50, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": 200, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": -30, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": 10, "exit_time": datetime.utcnow().isoformat()}
    ] * 10

    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=trades_data)
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch('app.monitor.send_alert_email') as mock_email:
        await monitor.check_strategy_performance(strategy)
        mock_email.assert_not_called()
        mock_supabase.table.return_value.update.assert_called_with({"health_status": "healthy"})

@pytest.mark.asyncio
async def test_check_strategy_performance_unhealthy(monitor, mock_supabase):
    mock_supabase.reset_mock()
    strategy = {"strategy_id": "s1", "name": "Strat1", "state": "Running"}
    trades_data = [
        {"pnl": -100, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": -50, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": -80, "exit_time": datetime.utcnow().isoformat()},
        {"pnl": -30, "exit_time": datetime.utcnow().isoformat()}
    ] * 15

    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=trades_data)
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch('app.monitor.send_alert_email') as mock_email:
        await monitor.check_strategy_performance(strategy)
        mock_email.assert_called_once()
        mock_supabase.table.return_value.update.assert_called_with({"health_status": "unhealthy"})

@pytest.mark.asyncio
async def test_check_strategy_performance_insufficient_trades(monitor, mock_supabase):
    mock_supabase.reset_mock()
    strategy = {"strategy_id": "s1", "name": "Strat1", "state": "Running"}
    trades_data = [{"pnl": 100, "exit_time": datetime.utcnow().isoformat()}] * 5

    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=trades_data)

    with patch('app.monitor.send_alert_email') as mock_email:
        await monitor.check_strategy_performance(strategy)
        mock_email.assert_not_called()
        mock_supabase.table.return_value.update.assert_not_called()
        mock_supabase.table.return_value.insert.assert_not_called()

@pytest.mark.asyncio
async def test_check_portfolio_metrics(monitor, mock_supabase):
    mock_supabase.reset_mock()
    strategies_data = [
        {"strategy_id": "s1", "name": "Strat1", "instrument": "EURUSD", "instrument_type": "Forex", "sizing": 10},
        {"strategy_id": "s2", "name": "Strat2", "instrument": "GC", "instrument_type": "Future", "sizing": 5}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=strategies_data)

    trades_data = []
    for i in range(30):
        trades_data.append({"strategy_id": "s1", "pnl": np.random.randn() * 10, "exit_time": (datetime.utcnow() - timedelta(days=i)).isoformat(), "cost": 0.5})
        trades_data.append({"strategy_id": "s2", "pnl": np.random.randn() * 15, "exit_time": (datetime.utcnow() - timedelta(days=i)).isoformat(), "cost": 0.3})
    mock_supabase.table.return_value.select.return_value.gte.return_value.execute.return_value = MagicMock(data=trades_data)

    weights_data = [{"strategy_id": "s1", "target_weight": 40}, {"strategy_id": "s2", "target_weight": 60}]
    mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=weights_data)

    with patch('app.monitor.regime.get_average_daily_volume', return_value=100000):
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

        with patch('app.monitor.send_alert_email') as mock_email:
            await monitor.check_portfolio_metrics()
            mock_supabase.table.return_value.insert.assert_called()