from datetime import date
import csv

import numpy as np
import pandas as pd

from reports.weekly.regime import (
    _condition_matches_any,
    build_regime_report,
    market_context,
    market_features,
)
from reports.weekly import build_summary, write_artifacts


def _history(count=700):
    index = pd.date_range(end="2026-11-20", periods=count, freq="B", tz="UTC")
    phase = np.arange(count)
    close = 100 + phase * 0.08 + np.sin(phase / 7) * 1.5
    return pd.DataFrame({"Open": close, "High": close + 1.0, "Low": close - 1.0, "Close": close}, index=index)


def _config():
    return {
        "lookbacks": {"atr_days": 14, "volatility_percentile_days": 252, "kaufman_days": 31, "sma_days": 200},
        "thresholds": {"volatility_low_below": 33, "volatility_high_above": 66, "kaufman_trend_min": 0.30},
    }


def test_market_features_calculate_regime_labels_and_context():
    prices = _history()
    features = market_features(prices, _config())
    assert features.iloc[-1]["volatility"] in {"LOW", "MID", "HIGH"}
    assert features.iloc[-1]["trend"] in {"TREND", "CHOP"}
    context = market_context(prices, _config(), as_of=date(2026, 11, 22))
    assert len(context["weekly_regimes"]) == 8
    assert 0 <= context["hist_percentile"] <= 100
    assert "episodes_gt5_total" in context and "return_heatmap" in context


def test_adverse_regime_hypothesis_supports_or_conditions():
    conditions = {"any": [{"price": ["BELOW"]}, {"volatility": ["HIGH"]}]}
    assert _condition_matches_any({"price": "BELOW", "volatility": "MID"}, conditions)
    assert not _condition_matches_any({"price": "ABOVE", "volatility": "MID"}, conditions)


def test_drawdown_episodes_are_counted_by_peak_to_trough_episode():
    from reports.weekly.regime import _episodes

    index = pd.date_range("2026-01-01", periods=5, freq="D", tz="UTC")
    close = pd.Series([100, 94, 96, 90, 97], index=index)
    result = _episodes(close, date(2026, 1, 5))
    assert result == {"episodes_gt5_total": 2, "episodes_gt5_last_12m": 2}


def test_regime_report_uses_reference_labels_and_simulator_skips_market_data(tmp_path):
    history = _history()
    report = build_regime_report(
        "2026-W47", {"portfolios": []}, backtest_dir=tmp_path,
        downloader=lambda ticker, end: history,
    )
    assert len(report["strategies"]) == 5
    monday = next(row for row in report["strategies"] if row["strategy_id"] == "MONDAY_BTCJPY")
    assert monday["ticker"] == "BTC-JPY"
    assert monday["hypothesis_confirmed"] is False
    assert monday["market_context"]["weekly_regimes"]

    fixture = build_regime_report("2026-W47", {"source": "simulator_fixture"}, backtest_dir=tmp_path, market_data_enabled=False)
    assert all(row["status"] == "SIMULATOR_NO_MARKET_DATA" for row in fixture["strategies"])


def test_backtest_is_conditioned_on_current_reference_market_regime(tmp_path):
    history = _history()
    path = tmp_path / "MONDAY_BTCJPY.csv"
    timestamp = history.index[-1].isoformat()
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["entry_time_utc", "exit_time_utc", "pnl_pct", "type"])
        writer.writeheader()
        for pnl in (1.0, -0.5):
            writer.writerow({"entry_time_utc": timestamp, "exit_time_utc": timestamp, "pnl_pct": pnl, "type": "long"})
    report = build_regime_report(
        "2026-W47", {"portfolios": []}, backtest_dir=tmp_path,
        downloader=lambda ticker, end: history,
    )
    monday = next(row for row in report["strategies"] if row["strategy_id"] == "MONDAY_BTCJPY")
    assert monday["conditional_backtest"]["status"] == "CONDITIONAL_BASELINE"
    assert monday["conditional_backtest"]["n_trades"] == 2


def test_weekly_report_renders_asset_and_live_heatmaps(tmp_path):
    history = _history()
    source = {"source": "monitor_api", "portfolios": [{"strategies": [{
        "id": "MONDAY_BTCJPY",
        "equity_samples": [{"ts": stamp.isoformat(), "equity": float(value)} for stamp, value in zip(history.index, history["Close"])],
    }]}]}
    summary = build_summary(
        "2026-W47", source, backtest_dir=tmp_path,
        now=pd.Timestamp("2026-11-22", tz="UTC").to_pydatetime(),
        market_downloader=lambda ticker, end: history,
    )
    output = write_artifacts(summary, tmp_path / "out")
    assert summary["strategies"][0]["regime_state"] in {"FAVORABLE_HYPOTHESIS", "ADVERSE_HYPOTHESIS", "MIXED_HYPOTHESIS"}
    assert summary["strategies"][1]["regime_state"] in {"FAVORABLE_HYPOTHESIS", "ADVERSE_HYPOTHESIS", "MIXED_HYPOTHESIS", "INFORMATIONAL"}
    assert (output / "check_regime.json").is_file()
    assert (output / "charts" / "MONDAY_BTCJPY_regime_heatmap.png").is_file()
