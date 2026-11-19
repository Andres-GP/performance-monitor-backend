"""Transparent, provisional EHI score construction and chart rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_ehi_config(path: Path = Path("config/ehi.yaml")) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _band(score: float, config: dict[str, Any]) -> str:
    if score < float(config["bands"]["red_below"]):
        return "RED"
    if score >= float(config["bands"]["green_from"]):
        return "GREEN"
    return "AMBER"


def score_ehi(backtest: dict[str, Any], regime: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    comparison = backtest.get("windows", {}).get(config["backtest_window"], {})
    percentiles = comparison.get("percentiles") or {}
    available = [float(percentiles[key]) for key in config["backtest_metrics"] if percentiles.get(key) is not None]
    if comparison.get("status") != "COMPARED" or not available:
        return {"ehi": None, "band": "N/A", "status": comparison.get("status", "NO_BACKTEST_SCORE"),
                "components": {"backtest_percentile": None, "regime_score": None},
                "component_states": {"backtest": comparison.get("status", "NO_BACKTEST_SCORE"), "regime": regime.get("status", "UNAVAILABLE")}}

    regime_status = regime.get("status", "UNAVAILABLE")
    if regime_status in {"MARKET_DATA_UNAVAILABLE", "SIMULATOR_NO_MARKET_DATA", "UNCONFIGURED"}:
        return {"ehi": None, "band": "N/A", "status": "MARKET_DATA_UNAVAILABLE",
                "components": {"backtest_percentile": sum(available) / len(available), "regime_score": None},
                "component_states": {"backtest": "AVAILABLE", "regime": regime_status}}

    if regime.get("status") == "INFORMATIONAL":
        regime_score = float(config["informational_regime_score"])
        regime_component_state = "INFORMATIONAL_NEUTRAL"
    elif not regime.get("hypothesis_confirmed", False):
        regime_score = float(config["unconfirmed_regime_score"])
        regime_component_state = "HYPOTHESIS_UNCONFIRMED_NEUTRAL"
    elif regime.get("verdict") == "ALIGNED":
        regime_score, regime_component_state = 100.0, "CONFIRMED_ALIGNED"
    elif regime.get("verdict") == "REVIEW":
        regime_score, regime_component_state = 0.0, "CONFIRMED_ADVERSE"
    else:
        regime_score, regime_component_state = 50.0, "CONFIRMED_MIXED"

    backtest_score = sum(available) / len(available)
    weights = config["weights"]
    total_weight = float(weights["backtest"]) + float(weights["regime"])
    score = (backtest_score * float(weights["backtest"]) + regime_score * float(weights["regime"])) / total_weight
    return {"ehi": round(score, 2), "band": _band(score, config), "status": "PROVISIONAL",
            "components": {"backtest_percentile": round(backtest_score, 2), "regime_score": regime_score},
            "component_states": {"backtest": "BOOTSTRAP_PERCENTILE", "regime": regime_component_state}}


def render_ehi_history(current_week: str, strategies: list[dict[str, Any]], output_root: Path) -> list[str]:
    import json
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    history: dict[str, dict[str, float]] = {}
    for path in output_root.glob("*/summary.json"):
        try:
            summary = json.loads(path.read_text())
            week = summary.get("week")
            if not week or week >= current_week:
                continue
            for row in summary.get("strategies", []):
                if row.get("ehi") is not None:
                    history.setdefault(row["strategy_id"], {})[week] = float(row["ehi"])
        except (OSError, ValueError, TypeError):
            continue
    for row in strategies:
        if row.get("ehi") is not None:
            history.setdefault(row["strategy_id"], {})[current_week] = float(row["ehi"])

    names = []
    chart_dir = output_root / current_week / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    for strategy_id, points in history.items():
        if len(points) < 2:
            continue
        weeks = sorted(points)
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.axhspan(0, 30, color="#f4cccc", alpha=0.5, label="Rojo <30")
        ax.axhspan(30, 70, color="#fff2cc", alpha=0.5, label="Ámbar 30–69")
        ax.axhspan(70, 100, color="#d9ead3", alpha=0.5, label="Verde ≥70")
        ax.plot(weeks, [points[week] for week in weeks], marker="o", color="#245a81")
        ax.set(title=f"{strategy_id} — EHI histórico (provisional)", ylabel="EHI (0–100)", ylim=(0, 100), xlabel="Semana ISO")
        ax.tick_params(axis="x", rotation=35)
        ax.legend(ncol=3, fontsize=8, loc="upper center")
        fig.tight_layout()
        filename = f"{strategy_id}_ehi.png"
        fig.savefig(chart_dir / filename, dpi=140)
        plt.close(fig)
        names.append(filename)
    return names
