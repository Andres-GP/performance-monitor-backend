import csv
from datetime import datetime, timedelta, timezone

from reports.weekly.backtest import (
    BOOTSTRAP_REPLICATES,
    bootstrap_comparison,
    equity_cone,
    reconcile_trades,
    strategy_backtest_analysis,
)
from reports.weekly import write_artifacts


def _trades(count=25):
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return [
        {
            "entry_time": (start + timedelta(days=i * 3)).isoformat(),
            "exit_time": (start + timedelta(days=i * 3, hours=2)).isoformat(),
            "profit": 10 if i % 2 == 0 else -5,
            "pnl_pct_equity": 0.5 if i % 2 == 0 else -0.25,
            "trade_type": "long",
            "entry_price": 100 + i,
            "exit_price": 101 + i,
            "volume": 0.1,
        }
        for i in range(count)
    ]


def _backtest_file(path, count=40):
    columns = ["entry_time_utc", "exit_time_utc", "pnl_pct", "type"]
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for i in range(count):
            entered = start + timedelta(days=i * 5)
            writer.writerow({
                "entry_time_utc": entered.isoformat(),
                "exit_time_utc": (entered + timedelta(hours=2)).isoformat(),
                "pnl_pct": 0.6 if i % 2 == 0 else -0.3,
                "type": "long",
            })


def test_missing_backtest_keeps_live_metrics_without_verdict(tmp_path):
    analysis = strategy_backtest_analysis("MONDAY_BTCJPY", _trades(3), tmp_path / "missing.csv", week_seed="2026-W47")
    assert analysis["status"] == "NO_BASELINE"
    assert analysis["live_metrics"]["all"]["n_trades"] == 3
    assert analysis["windows"]["all"]["verdict"] is None


def test_bootstrap_comparison_is_deterministic_and_marks_sample_size():
    live = _trades(20)
    backtest = [{"pnl_pct": 0.6 if i % 2 == 0 else -0.3, "type": "long"} for i in range(40)]
    first = bootstrap_comparison(live, backtest, seed=42)
    second = bootstrap_comparison(live, backtest, seed=42)
    assert first == second
    assert first["status"] == "COMPARED"
    assert first["bootstrap"] == {"replicates": BOOTSTRAP_REPLICATES, "block_size": 3, "sample_trades": 20}
    assert set(first["percentiles"]) == {"expectancy_pct", "profit_factor", "win_rate"}


def test_backtest_csv_produces_windows_bootstrap_and_equity_cone(tmp_path):
    path = tmp_path / "MONDAY_BTCJPY.csv"
    _backtest_file(path)
    analysis = strategy_backtest_analysis("MONDAY_BTCJPY", _trades(25), path, week_seed="2026-W47")
    assert analysis["status"] == "COMPARED"
    assert analysis["windows"]["last_20_trades"]["n_trades"] == 20
    assert analysis["cone"]["trade_index"][-1] == 25
    assert set(analysis["cone"]["bands"]) == {"p5", "p25", "p50", "p75", "p95"}


def test_trade_reconciliation_flags_price_and_reference_only_rows(tmp_path):
    reference = tmp_path / "engine.csv"
    reference.write_text(
        "entry_time_utc,entry_price,exit_price,volume,type\n"
        "2026-05-01T00:00:00Z,99,101,0.1,long\n"
        "2026-06-30T00:00:00Z,100,101,0.1,long\n"
    )
    result = reconcile_trades(_trades(1), reference)
    assert result["status"] == "RECONCILED"
    assert {row["status"] for row in result["mismatches"]} == {"RECON_MISMATCH", "REFERENCE_ONLY"}


def test_equity_cone_can_use_small_test_replicate_count():
    cone = equity_cone(_trades(25), [{"pnl_pct": 0.3 if i % 2 else -0.1} for i in range(30)], seed=5, replicates=20)
    assert cone["replicates"] == 20
    assert len(cone["bands"]["p50"]) == len(cone["trade_index"])


def test_writer_renders_cone_chart_when_comparison_is_available(tmp_path):
    cone = equity_cone(_trades(20), [{"pnl_pct": 0.4 if i % 2 else -0.2} for i in range(30)], seed=7, replicates=20)
    analysis = {"cone": cone, "windows": {}, "status": "COMPARED", "reconciliation": {"status": "NO_RECON_LOG"}}
    summary = {
        "week": "2026-W47",
        "status": "PENDING_ANALYSIS",
        "strategies": [{
            "strategy_id": "MONDAY_BTCJPY", "backtest_state": "COMPARED",
            "regime_state": "PENDING_STEP_17", "status": "COMPARED", "ehi": None,
            "backtest_analysis": analysis,
                "regime_analysis": {"status": "PENDING_STEP_17", "verdict": None},
        }],
    }
    folder = write_artifacts(summary, tmp_path)
    assert (folder / "charts" / "MONDAY_BTCJPY_cone.png").is_file()
