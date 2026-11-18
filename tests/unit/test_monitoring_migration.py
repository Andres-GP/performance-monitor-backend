import re
import sqlite3
from pathlib import Path

import pytest


MIGRATIONS = Path(__file__).parents[2] / "db" / "migrations"
UP = MIGRATIONS / "0001_monitoring_core.up.sql"
DOWN = MIGRATIONS / "0001_monitoring_core.down.sql"


def run_sqlite_compatible_migration(connection, sql):
    # SQLite is the local migration test harness; the committed migration targets PostgreSQL.
    sqlite_sql = re.sub(
        r"BIGINT\s+GENERATED\s+BY\s+DEFAULT\s+AS\s+IDENTITY\s+PRIMARY\s+KEY",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        sql,
        flags=re.IGNORECASE,
    )
    connection.executescript(sqlite_sql)


def test_monitoring_migration_up_creates_tables_indexes_and_constraints():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    run_sqlite_compatible_migration(connection, UP.read_text(encoding="utf-8"))

    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "portfolio", "strategy", "event_raw", "trade", "equity_sample", "daily_stats",
        "heartbeat", "alert", "rule_state", "unregistered_source",
    } <= tables

    indexes = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert "event_raw_strategy_ts_idx" in indexes
    assert "heartbeat_strategy_ts_idx" in indexes
    assert "alert_active_strategy_rule_idx" in indexes

    connection.execute("INSERT INTO portfolio (id, broker, daily_dd_limit_pct, total_dd_limit_pct) VALUES ('P', 'Broker', 3, 8)")
    connection.execute("INSERT INTO strategy (id, portfolio_id, strategy_name_prefix, magic, timeframe, vehicle, direction) VALUES ('S', 'P', 'S_', 1, 'H1', 'CFD', 'long')")
    connection.execute("INSERT INTO event_raw (idempotency_key, strategy_id, event_type, payload) VALUES ('event-1', 'S', 'heartbeat', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO event_raw (idempotency_key, strategy_id, event_type, payload) VALUES ('event-1', 'S', 'heartbeat', '{}')")


def test_monitoring_migration_down_removes_schema():
    connection = sqlite3.connect(":memory:")
    run_sqlite_compatible_migration(connection, UP.read_text(encoding="utf-8"))
    run_sqlite_compatible_migration(connection, DOWN.read_text(encoding="utf-8"))

    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert not tables.intersection({
        "portfolio", "strategy", "event_raw", "trade", "equity_sample", "daily_stats",
        "heartbeat", "alert", "rule_state", "unregistered_source",
    })
