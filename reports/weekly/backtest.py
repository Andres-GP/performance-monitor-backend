"""Deterministic live/backtest statistics and block-bootstrap comparison."""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

UTC = timezone.utc
BOOTSTRAP_REPLICATES = 10_000
BLOCK_SIZE = 3


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _trade_return(row: dict[str, Any]) -> float | None:
    for key in ("pnl_pct", "pnl_pct_equity", "return_pct"):
        value = row.get(key)
        if value not in (None, ""):
            return float(value)
    return None


def _profit(row: dict[str, Any]) -> float:
    return float(row.get("profit", row.get("pnl", row.get("pnl_pct", 0))) or 0)


def read_backtest(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"entry_time_utc", "exit_time_utc", "pnl_pct", "type"}
    if rows and not required.issubset(rows[0]):
        raise ValueError(f"{path} must contain columns: {', '.join(sorted(required))}")
    return rows


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    profits = np.asarray([_profit(row) for row in trades], dtype=float)
    returns = [_trade_return(row) for row in trades]
    known_returns = np.asarray([value for value in returns if value is not None], dtype=float)
    gross_wins = float(profits[profits > 0].sum())
    gross_losses = float(-profits[profits < 0].sum())
    hold_values = []
    dates = []
    for row in trades:
        hold = row.get("hold_minutes")
        entered, exited = _dt(row.get("entry_time_utc") or row.get("entry_time")), _dt(row.get("exit_time_utc") or row.get("exit_time"))
        if hold not in (None, ""):
            hold_values.append(float(hold))
        elif entered and exited:
            hold_values.append((exited - entered).total_seconds() / 60)
        if exited:
            dates.append(exited)
    months = max((max(dates) - min(dates)).total_seconds() / (86400 * 30.4375), 1 / 30.4375) if len(dates) > 1 else None
    max_drawdown = None
    if known_returns.size:
        curve = np.cumprod(1 + known_returns / 100)
        peaks = np.maximum.accumulate(np.insert(curve, 0, 1.0))[1:]
        max_drawdown = float(np.max(np.maximum(0, (peaks - curve) / peaks)) * 100)
    streak = max_streak = 0
    for profit in profits:
        if profit < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    loss_values = known_returns[known_returns < 0]
    win_values = known_returns[known_returns > 0]
    return {
        "n_trades": len(trades),
        "win_rate": float(np.mean(profits > 0) * 100) if len(trades) else None,
        "profit_factor": gross_wins / gross_losses if gross_losses else (None if gross_wins == 0 else "Infinity"),
        "expectancy_pct": float(known_returns.mean()) if known_returns.size else None,
        "avg_win_pct": float(win_values.mean()) if win_values.size else None,
        "avg_loss_pct": float(loss_values.mean()) if loss_values.size else None,
        "avg_hold_minutes": float(np.mean(hold_values)) if hold_values else None,
        "trades_per_month": len(trades) / months if months else None,
        "max_drawdown_pct": max_drawdown,
        "max_loss_streak": max_streak,
    }


def _block_sample(values: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    blocks = math.ceil(n / BLOCK_SIZE)
    starts = rng.integers(0, len(values), size=blocks)
    indices = (starts[:, None] + np.arange(BLOCK_SIZE)[None, :]) % len(values)
    return values[indices.reshape(-1)[:n]]


def _percentile(distribution: list[float], observed: float) -> float:
    finite = np.asarray([value for value in distribution if math.isfinite(value)], dtype=float)
    if not finite.size:
        return 50.0
    return float(np.mean(finite <= observed) * 100)


def bootstrap_comparison(live: list[dict[str, Any]], backtest: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    live_metrics = _metrics(live)
    n = len(live)
    if n < 20:
        return {"status": "INSUFFICIENT_DATA", "n_trades": n, "live": live_metrics, "percentiles": None, "verdict": None}
    if not backtest:
        return {"status": "NO_BASELINE", "n_trades": n, "live": live_metrics, "percentiles": None, "verdict": None}
    baseline_returns = np.asarray([_trade_return(row) for row in backtest if _trade_return(row) is not None], dtype=float)
    if not baseline_returns.size:
        return {"status": "INVALID_BASELINE", "n_trades": n, "live": live_metrics, "percentiles": None, "verdict": None}

    rng = np.random.default_rng(seed)
    distributions = {"expectancy_pct": [], "profit_factor": [], "win_rate": []}
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = _block_sample(baseline_returns, n, rng)
        positive, negative = sample[sample > 0], sample[sample < 0]
        gross_loss = -float(negative.sum())
        distributions["expectancy_pct"].append(float(sample.mean()))
        distributions["profit_factor"].append(float(positive.sum()) / gross_loss if gross_loss else math.inf)
        distributions["win_rate"].append(float(np.mean(sample > 0) * 100))
    observed = {
        "expectancy_pct": live_metrics["expectancy_pct"],
        "profit_factor": live_metrics["profit_factor"],
        "win_rate": live_metrics["win_rate"],
    }
    percentiles = {
        key: _percentile(values, float(observed[key]))
        for key, values in distributions.items()
        if observed[key] is not None and observed[key] != "Infinity"
    }
    outside = [key for key, value in percentiles.items() if value < 5 or value > 95]
    return {
        "status": "COMPARED",
        "n_trades": n,
        "live": live_metrics,
        "percentiles": percentiles,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "block_size": BLOCK_SIZE, "sample_trades": n},
        "verdict": "OUTSIDE_BOOTSTRAP_90" if outside else "WITHIN_BOOTSTRAP_90",
        "outside_metrics": outside,
    }


def equity_cone(live: list[dict[str, Any]], backtest: list[dict[str, Any]], *, seed: int, replicates: int = BOOTSTRAP_REPLICATES, max_points: int = 1000) -> dict[str, Any] | None:
    live_returns = np.asarray([_trade_return(row) for row in live if _trade_return(row) is not None], dtype=float)
    baseline = np.asarray([_trade_return(row) for row in backtest if _trade_return(row) is not None], dtype=float)
    if not live_returns.size or not baseline.size:
        return None
    n = len(live_returns)
    x = np.unique(np.linspace(1, n, min(n, max_points), dtype=int))
    points = np.empty((replicates, len(x)), dtype=np.float32)
    rng = np.random.default_rng(seed)
    chunk_size = max(1, min(250, replicates))
    block_offsets = np.arange(BLOCK_SIZE)[None, None, :]
    for start in range(0, replicates, chunk_size):
        count = min(chunk_size, replicates - start)
        n_blocks = math.ceil(n / BLOCK_SIZE)
        block_starts = rng.integers(0, len(baseline), size=(count, n_blocks, 1))
        indices = ((block_starts + block_offsets) % len(baseline)).reshape(count, -1)[:, :n]
        paths = np.cumprod(1 + baseline[indices] / 100, axis=1)
        points[start:start + count] = paths[:, x - 1]
    path = np.cumprod(1 + live_returns / 100)
    return {
        "trade_index": x.tolist(),
        "live_equity_index": path[x - 1].tolist(),
        "bands": {
            f"p{percentile}": np.percentile(points, percentile, axis=0).astype(float).tolist()
            for percentile in (5, 25, 50, 75, 95)
        },
        "replicates": replicates,
        "block_size": BLOCK_SIZE,
    }


def reconcile_trades(live: list[dict[str, Any]], source_file: Path | None) -> dict[str, Any]:
    if source_file is None:
        candidates = (
            Path("Common/Files/weekly_momentum_log.csv"),
            Path("Common/Files/weekly_momentum_trades.csv"),
        )
        source_file = next((path for path in candidates if path.exists()), None)
    if source_file is None or not source_file.exists():
        return {"status": "NO_RECON_LOG", "mismatches": []}
    with source_file.open(newline="", encoding="utf-8-sig") as handle:
        expected = list(csv.DictReader(handle))
    def key(row):
        stamp = row.get("entry_time_utc") or row.get("entry_time") or row.get("entry_date") or ""
        return str(stamp)[:10]
    expected_by_day = {key(row): row for row in expected}
    mismatches = []
    matched = 0
    for row in live:
        reference = expected_by_day.get(key(row))
        if reference is None:
            mismatches.append({"entry_date": key(row), "status": "LIVE_ONLY"})
            continue
        matched += 1
        differences = {}
        aliases = {"entry_price": ("entry_price", "price_entry"), "exit_price": ("exit_price", "price_exit"), "volume": ("volume", "lots"), "trade_type": ("type", "direction", "decision")}
        for field, choices in aliases.items():
            live_value = row.get(field)
            expected_value = next((reference[name] for name in choices if reference.get(name) not in (None, "")), None)
            if live_value is not None and expected_value is not None:
                try:
                    if field == "trade_type":
                        expected_direction = {"buy": "long", "sell": "short"}.get(str(expected_value).lower(), str(expected_value).lower())
                        differs = str(live_value).lower() != expected_direction
                    else:
                        differs = not math.isclose(float(live_value), float(expected_value), rel_tol=1e-6, abs_tol=1e-8)
                except (TypeError, ValueError):
                    differs = str(live_value) != str(expected_value)
                if differs:
                    differences[field] = {"live": live_value, "reference": expected_value}
        if differences:
            mismatches.append({"entry_date": key(row), "status": "RECON_MISMATCH", "differences": differences})
    for day in expected_by_day.keys() - {key(row) for row in live}:
        mismatches.append({"entry_date": day, "status": "REFERENCE_ONLY"})
    return {"status": "RECONCILED", "matched": matched, "mismatches": mismatches, "source_file": str(source_file)}


def strategy_backtest_analysis(
    strategy_id: str,
    trades: list[dict[str, Any]],
    backtest_file: Path,
    *,
    recon_file: Path | None = None,
    week_seed: str = "",
) -> dict[str, Any]:
    try:
        year_text, week_text = week_seed.split("-W", 1)
        as_of = datetime.combine(datetime.fromisocalendar(int(year_text), int(week_text), 7).date(), datetime.max.time(), UTC)
    except (ValueError, TypeError):
        as_of = datetime.now(UTC)
    ordered = sorted(
        (row for row in trades if (_dt(row.get("exit_time_utc") or row.get("exit_time")) or as_of) <= as_of),
        key=lambda row: _dt(row.get("exit_time_utc") or row.get("exit_time")) or datetime.min.replace(tzinfo=UTC),
    )
    cutoff = as_of - timedelta(weeks=26)
    windows = {
        "all": ordered,
        "last_26_weeks": [row for row in ordered if (_dt(row.get("exit_time")) or datetime.min.replace(tzinfo=UTC)) >= cutoff],
        "last_20_trades": ordered[-20:],
        "last_50_trades": ordered[-50:],
    }
    live_metrics = {name: _metrics(rows) for name, rows in windows.items()}
    reconciliation = reconcile_trades(ordered, recon_file)
    if not backtest_file.exists():
        return {
            "status": "NO_BASELINE", "live_metrics": live_metrics,
            "backtest_metrics": None, "windows": {name: {"status": "NO_BASELINE", "verdict": None} for name in windows},
            "reconciliation": reconciliation, "cone": None,
        }
    baseline = read_backtest(backtest_file)
    if not baseline:
        return {
            "status": "NO_BASELINE", "live_metrics": live_metrics,
            "backtest_metrics": None, "windows": {name: {"status": "NO_BASELINE", "verdict": None} for name in windows},
            "reconciliation": reconciliation, "cone": None,
        }
    comparisons = {}
    seed_root = hashlib.sha256(f"{strategy_id}:{week_seed}".encode()).digest()
    for index, (name, rows) in enumerate(windows.items()):
        seed = int.from_bytes(seed_root[index:index + 4], "big")
        comparisons[name] = bootstrap_comparison(rows, baseline, seed=seed)
    cone = equity_cone(ordered, baseline, seed=int.from_bytes(seed_root[:4], "big"))
    return {
        "status": "COMPARED" if any(row["status"] == "COMPARED" for row in comparisons.values()) else "INSUFFICIENT_DATA",
        "live_metrics": live_metrics,
        "backtest_metrics": _metrics(baseline),
        "windows": comparisons,
        "reconciliation": reconciliation,
        "cone": cone,
    }
