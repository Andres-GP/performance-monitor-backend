"""Reference-market regimes and return heatmap data for Step 17."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import yaml

from .backtest import read_backtest

UTC = timezone.utc


def load_regime_config(path: Path = Path("config/regimes.yaml")) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def download_history(ticker: str, *, end: date) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download(
        ticker, start="2009-01-01", end=(end + timedelta(days=1)).isoformat(),
        interval="1d", auto_adjust=True, progress=False, threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def _condition_matches(current: dict[str, Any], conditions: dict[str, list[str]]) -> bool:
    return bool(conditions) and all(current.get(key) in expected for key, expected in conditions.items())


def _condition_matches_any(current: dict[str, Any], conditions: dict[str, Any]) -> bool:
    alternatives = conditions.get("any", [])
    if alternatives:
        return any(_condition_matches(current, alternative) for alternative in alternatives)
    return _condition_matches(current, conditions)


def market_features(prices: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    frame = prices.copy()
    frame.columns = [str(column).lower().replace(" ", "_") for column in frame.columns]
    if "close" not in frame:
        raise ValueError("market history is missing close")
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame.get("high", close), errors="coerce")
    low = pd.to_numeric(frame.get("low", close), errors="coerce")
    previous = close.shift(1)
    true_range = pd.concat([(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr_window = int(config["lookbacks"]["atr_days"])
    vol_window = int(config["lookbacks"]["volatility_percentile_days"])
    trend_window = int(config["lookbacks"]["kaufman_days"])
    sma_window = int(config["lookbacks"]["sma_days"])
    atr_pct = true_range.rolling(atr_window, min_periods=atr_window).mean() / close * 100
    vol_pct = atr_pct.rolling(vol_window, min_periods=vol_window).apply(
        lambda values: float(pd.Series(values).rank(pct=True).iloc[-1] * 100), raw=False,
    )
    direction_change = close.diff(trend_window).abs()
    path_length = close.diff().abs().rolling(trend_window, min_periods=trend_window).sum()
    efficiency = direction_change / path_length.replace(0, np.nan)
    result = pd.DataFrame(index=pd.to_datetime(frame.index, utc=True))
    result["close"] = close.to_numpy()
    result["atr_pct"] = atr_pct.to_numpy()
    result["volatility_percentile"] = vol_pct.to_numpy()
    result["efficiency_ratio"] = efficiency.to_numpy()
    result["return_31d_pct"] = close.pct_change(trend_window).to_numpy() * 100
    result["sma_200"] = close.rolling(sma_window, min_periods=sma_window).mean().to_numpy()
    low_edge = float(config["thresholds"]["volatility_low_below"])
    high_edge = float(config["thresholds"]["volatility_high_above"])
    trend_edge = float(config["thresholds"]["kaufman_trend_min"])
    result["volatility"] = np.select(
        [result["volatility_percentile"] < low_edge, result["volatility_percentile"] > high_edge],
        ["LOW", "HIGH"], default="MID",
    )
    result["trend"] = np.where(result["efficiency_ratio"] >= trend_edge, "TREND", "CHOP")
    result["direction"] = np.where(result["return_31d_pct"] >= 0, "UP", "DOWN")
    result["price"] = np.where(result["close"] >= result["sma_200"], "ABOVE", "BELOW")
    return result


def _episodes(close: pd.Series, as_of: date) -> dict[str, int]:
    drawdown = close / close.cummax() - 1
    below = drawdown <= -0.05
    cutoff = pd.Timestamp(as_of - timedelta(days=365), tz="UTC")
    positions = np.flatnonzero(below.to_numpy())
    groups = np.split(positions, np.flatnonzero(np.diff(positions) > 1) + 1) if len(positions) else []
    trough_dates = [drawdown.index[group[np.argmin(drawdown.iloc[group].to_numpy())]] for group in groups]
    return {
        "episodes_gt5_total": int(len(trough_dates)),
        "episodes_gt5_last_12m": int(sum(stamp >= cutoff for stamp in trough_dates)),
    }


def _heatmap(series: pd.Series) -> dict[str, list[dict[str, Any]]]:
    values = series.dropna().astype(float)
    if values.empty:
        return {"weekly": [], "monthly": []}
    weekly = values.resample("W-FRI").last().pct_change().dropna().tail(12) * 100
    monthly_close = values.resample("ME").last()
    monthly_returns = monthly_close.pct_change().dropna() * 100
    return {
        "weekly": [{"period": stamp.date().isoformat(), "return_pct": float(value)} for stamp, value in weekly.items()],
        "monthly": [{"year": int(stamp.year), "month": int(stamp.month), "return_pct": float(value)} for stamp, value in monthly_returns.items()],
    }


def market_context(prices: pd.DataFrame, config: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    features = market_features(prices, config)
    if features.empty:
        raise ValueError("market history is too short for regime lookbacks")
    valid = features.dropna(subset=["atr_pct", "volatility_percentile", "efficiency_ratio", "sma_200"])
    if valid.empty:
        raise ValueError("market history is too short for 252-day regimes and 200-day SMA")
    current = valid.iloc[-1]
    current_date = valid.index[-1]
    atr_history = features["atr_pct"].dropna()
    history_percentile = float(atr_history.rank(pct=True).iloc[-1] * 100)
    weekly_features = valid.resample("W-FRI").last().tail(8)
    weekly_regimes = [
        {
            "week_ending": stamp.date().isoformat(), "volatility": row.volatility,
            "trend": row.trend, "direction": row.direction, "price": row.price,
            "atr_pct": float(row.atr_pct), "volatility_percentile_252d": float(row.volatility_percentile),
        }
        for stamp, row in weekly_features.iterrows()
    ]
    close = pd.Series(features["close"].dropna().to_numpy(), index=features["close"].dropna().index)
    return {
        "as_of": current_date.date().isoformat(),
        "volatility": str(current.volatility), "trend": str(current.trend),
        "direction": str(current.direction), "price": str(current.price),
        "atr_pct_14": float(current.atr_pct),
        "volatility_percentile_252d": float(current.volatility_percentile),
        "hist_percentile": history_percentile,
        **_episodes(close, as_of),
        "history_start": close.index[0].date().isoformat(),
        "weekly_regimes": weekly_regimes,
        "return_heatmap": _heatmap(close),
        "_features": features,
    }


def _conditional_backtest(path: Path, features: pd.DataFrame, current: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NO_BASELINE", "n_trades": 0, "expectancy_pct": None, "profit_factor": None}
    trades = read_backtest(path)
    selected_returns = []
    for trade in trades:
        stamp = trade.get("entry_time_utc") or trade.get("entry_time")
        if not stamp:
            continue
        ts = pd.Timestamp(stamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        prior = features.loc[features.index <= ts].dropna(subset=["volatility_percentile", "efficiency_ratio", "sma_200"])
        if prior.empty:
            continue
        row = prior.iloc[-1]
        if all(str(row[key]) == current[key] for key in ("volatility", "trend", "direction", "price")):
            selected_returns.append(float(trade["pnl_pct"]))
    if not selected_returns:
        return {"status": "NO_MATCHING_REGIME", "n_trades": 0, "expectancy_pct": None, "profit_factor": None}
    values = np.asarray(selected_returns)
    wins, losses = values[values > 0], values[values < 0]
    return {
        "status": "CONDITIONAL_BASELINE",
        "n_trades": int(len(values)),
        "expectancy_pct": float(values.mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.size else None,
    }


def _strategy_heatmap(strategy: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows = strategy.get("equity_samples") or []
    if not rows:
        return {"weekly": [], "monthly": []}
    series = pd.Series(
        [float(row["equity"]) for row in rows],
        index=pd.to_datetime([row["ts"] for row in rows], utc=True),
    ).sort_index()
    return _heatmap(series)


def build_regime_report(
    week: str,
    source: dict[str, Any],
    *,
    backtest_dir: Path,
    config_path: Path = Path("config/regimes.yaml"),
    downloader: Callable[..., pd.DataFrame] = download_history,
    reference_logs: dict[str, Path | None] | None = None,
    market_data_enabled: bool = True,
) -> dict[str, Any]:
    config = load_regime_config(config_path)
    year_text, week_text = week.split("-W")
    as_of = date.fromisocalendar(int(year_text), int(week_text), 7)
    source_by_id = {}
    for portfolio in source.get("portfolios", []):
        for strategy in portfolio.get("strategies", []):
            source_by_id[strategy.get("id", "")] = strategy
    market_by_ticker = {}
    for ticker in set(config["market_tickers"].values()):
        if not market_data_enabled:
            market_by_ticker[ticker] = {"status": "SIMULATOR_NO_MARKET_DATA"}
            continue
        try:
            market_by_ticker[ticker] = market_context(downloader(ticker, end=as_of), config, as_of=as_of)
        except Exception as exc:
            market_by_ticker[ticker] = {"status": "MARKET_DATA_UNAVAILABLE", "error": str(exc)}
    checks = []
    for strategy_id, rule in config["strategies"].items():
        ticker = config["market_tickers"][rule["instrument"]]
        market = market_by_ticker[ticker]
        live = source_by_id.get(strategy_id, {})
        if market.get("status") in {"MARKET_DATA_UNAVAILABLE", "SIMULATOR_NO_MARKET_DATA"}:
            checks.append({
                "strategy_id": strategy_id, "instrument": rule["instrument"], "ticker": ticker,
                "status": market["status"], "verdict": None,
                "error": market.get("error"), "hypothesis_confirmed": rule.get("hypothesis_confirmed", False),
                "live_return_heatmap": _strategy_heatmap(live),
            })
            continue
        current = {key: market[key] for key in ("volatility", "trend", "direction", "price")}
        adverse = _condition_matches_any(current, rule.get("adverse", {}))
        favorable = _condition_matches(current, rule.get("favorable", {}))
        if rule.get("informational_only"):
            status, verdict = "INFORMATIONAL", None
        elif adverse:
            status, verdict = "ADVERSE_HYPOTHESIS", "REVIEW"
        elif favorable:
            status, verdict = "FAVORABLE_HYPOTHESIS", "ALIGNED"
        else:
            status, verdict = "MIXED_HYPOTHESIS", "WATCH"
        features = market["_features"]
        conditional = _conditional_backtest(backtest_dir / f"{strategy_id}.csv", features, current)
        context = {key: value for key, value in market.items() if key != "_features"}
        checks.append({
            "strategy_id": strategy_id,
            "instrument": rule["instrument"],
            "ticker": ticker,
            "status": status,
            "verdict": verdict,
            "hypothesis_confirmed": rule.get("hypothesis_confirmed", False),
            "current_regime": current,
            "favorable_hypothesis": rule.get("favorable", {}),
            "adverse_hypothesis": rule.get("adverse", {}),
            "conditional_backtest": conditional,
            "market_context": context,
            "live_return_heatmap": _strategy_heatmap(live),
            "factor_note": (
                "Momentum ETHUSD is a single-factor exposure; inspect overlap/correlation with MONDAY_BTCJPY (CRYPTO_LONG) during momentum stress."
                if strategy_id == "WEEKLYMOM_ETHUSD" else None
            ),
        })
    return {
        "week": week,
        "market_data_note": "Reference Yahoo Finance prices; they may differ from the broker CFD. Strategy regime hypotheses are unconfirmed.",
        "strategies": checks,
        "markets": {ticker: {key: value for key, value in report.items() if key != "_features"} for ticker, report in market_by_ticker.items()},
    }


def render_regime_heatmaps(report: dict[str, Any], output_dir: Path) -> None:
    """Render asset and strategy return heatmaps with labels and percent units."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    markets = report.get("markets", {})
    market_for_strategy = {}
    for row in report.get("strategies", []):
        market_for_strategy[row["strategy_id"]] = markets.get(row["ticker"], {}).get("return_heatmap", {})

    def monthly_matrix(rows):
        if not rows:
            return [], np.empty((0, 12))
        years = sorted({item["year"] for item in rows})
        matrix = np.full((len(years), 12), np.nan)
        by_year = {year: index for index, year in enumerate(years)}
        for item in rows:
            matrix[by_year[item["year"]], item["month"] - 1] = item["return_pct"]
        return years, matrix

    for row in report.get("strategies", []):
        if row.get("status") not in {"INFORMATIONAL", "FAVORABLE_HYPOTHESIS", "ADVERSE_HYPOTHESIS", "MIXED_HYPOTHESIS"}:
            continue
        asset = market_for_strategy.get(row["strategy_id"], {})
        live = row.get("live_return_heatmap", {})
        fig, axes = plt.subplots(2, 2, figsize=(12, 7), gridspec_kw={"height_ratios": [1, 2]})
        for axis, series, title in (
            (axes[0, 0], asset.get("weekly", []), "Activo — retornos semanales"),
            (axes[0, 1], live.get("weekly", []), "Estrategia live — retornos semanales"),
        ):
            axis.axhline(0, color="#666", linewidth=0.7)
            if series:
                colors = ["#2e8b57" if item["return_pct"] >= 0 else "#e88439" for item in series]
                bars = axis.bar(range(len(series)), [item["return_pct"] for item in series], color=colors)
                axis.bar_label(bars, fmt="%.1f", fontsize=6, padding=1)
                axis.set_xticks(range(len(series)), [item["period"][5:] for item in series], rotation=45, ha="right")
            else:
                axis.text(0.5, 0.5, "Sin series disponibles", ha="center", va="center", transform=axis.transAxes)
            axis.set(title=title, ylabel="Retorno (%)")
        for axis, series, title in (
            (axes[1, 0], asset.get("monthly", []), "Activo — retornos mensuales"),
            (axes[1, 1], live.get("monthly", []), "Estrategia live — retornos mensuales"),
        ):
            years, matrix = monthly_matrix(series)
            if len(years):
                colors = LinearSegmentedColormap.from_list("orange_green", ["#e88439", "#f6f3df", "#2e8b57"])
                mesh = axis.imshow(matrix, aspect="auto", cmap=colors, vmin=-10, vmax=10)
                axis.set_yticks(range(len(years)), years)
                axis.set_xticks(range(12), ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
                for y in range(matrix.shape[0]):
                    for month in range(matrix.shape[1]):
                        value = matrix[y, month]
                        if np.isfinite(value):
                            axis.text(month, y, f"{value:.1f}", ha="center", va="center", fontsize=6, color="#111")
                fig.colorbar(mesh, ax=axis, fraction=0.046, pad=0.04, label="Retorno (%)")
            else:
                axis.text(0.5, 0.5, "Sin series disponibles", ha="center", va="center", transform=axis.transAxes)
                axis.set_xticks([])
                axis.set_yticks([])
            axis.set_title(title)
        fig.suptitle(f"{row['strategy_id']} — {row['ticker']} (referencia de mercado, no CFD)")
        fig.tight_layout()
        fig.savefig(output_dir / f"{row['strategy_id']}_regime_heatmap.png", dpi=140)
        plt.close(fig)
