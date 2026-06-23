import pytest
from datetime import datetime
from unittest.mock import MagicMock
from app.supabase_client import upsert_strategy, insert_trade, insert_snapshot
from app.models import StrategyInfo, TradeRecord, PerformanceSnapshot

def test_upsert_strategy_success(mocker):
    mock_supabase = mocker.patch('app.supabase_client.supabase')
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "test_123"}])

    strategy = StrategyInfo(
        strategy_id="test_123",
        name="TestStrategy",
        instrument="EURUSD",
        start_date=datetime.utcnow(),
        state="Running"
    )

    result = upsert_strategy(strategy)
    assert len(result) == 1
    mock_supabase.table.return_value.upsert.assert_called_once()

def test_insert_trade_success(mocker):
    mock_supabase = mocker.patch('app.supabase_client.supabase')
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "trade_1"}])

    trade = TradeRecord(
        strategy_id="test_123",
        instrument="EURUSD",
        entry_time=datetime.utcnow(),
        exit_time=datetime.utcnow(),
        quantity=1,
        entry_price=1.1000,
        exit_price=1.1020,
        pnl=20.0,
        direction="Long"
    )

    result = insert_trade(trade)
    assert len(result) == 1
    mock_supabase.table.return_value.insert.assert_called_once()

def test_insert_snapshot_success(mocker):
    mock_supabase = mocker.patch('app.supabase_client.supabase')
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "snapshot_1"}])

    snapshot = PerformanceSnapshot(
        strategy_id="test_123",
        timestamp=datetime.utcnow(),
        total_trades=10,
        total_pnl=500.0
    )

    result = insert_snapshot(snapshot)
    assert len(result) == 1
    mock_supabase.table.return_value.insert.assert_called_once()

def test_upsert_strategy_serialization(mocker):
    mock_supabase = mocker.patch('app.supabase_client.supabase')
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

    now = datetime.utcnow()
    strategy = StrategyInfo(
        strategy_id="test_123",
        name="Test",
        instrument="EURUSD",
        start_date=now,
        state="Running"
    )

    upsert_strategy(strategy)
    call_args = mock_supabase.table.return_value.upsert.call_args[0][0]
    assert isinstance(call_args["start_date"], str)

def test_insert_trade_serialization(mocker):
    mock_supabase = mocker.patch('app.supabase_client.supabase')
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    now = datetime.utcnow()
    trade = TradeRecord(
        strategy_id="test_123",
        instrument="EURUSD",
        entry_time=now,
        exit_time=now,
        quantity=1,
        entry_price=1.1,
        exit_price=1.12,
        pnl=20,
        direction="Long"
    )

    insert_trade(trade)
    call_args = mock_supabase.table.return_value.insert.call_args[0][0]
    assert isinstance(call_args["entry_time"], str)
    assert isinstance(call_args["exit_time"], str)