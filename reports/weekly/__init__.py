"""Weekly review artifact generation; later steps add deterministic checks."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

from app.monitoring.strategies import load_registry

UTC = timezone.utc


def iso_week(value: str) -> str:
    if value == "auto":
        now = datetime.now(UTC).date()
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    try:
        year_text, week_text = value.split("-W", 1)
        date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError) as exc:
        raise ValueError("week must be 'auto' or ISO YYYY-Www") from exc
    return f"{int(year_text)}-W{int(week_text):02d}"


def _fetch_live(api_url: str, token: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    response = session.get(f"{api_url.rstrip('/')}/portfolios?limit=500", timeout=30)
    response.raise_for_status()
    page = response.json()
    portfolios = []
    for item in page.get("items", []):
        detail = session.get(f"{api_url.rstrip('/')}/portfolios/{item['id']}", timeout=30)
        detail.raise_for_status()
        portfolios.append(detail.json())
    return {"portfolios": portfolios, "source": "monitor_api"}


def build_summary(week: str, source: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    registry = load_registry()
    live_by_id = {}
    for portfolio in source.get("portfolios", []):
        for strategy in portfolio.get("strategies", []):
            live_by_id[strategy.get("id", "")] = strategy

    strategies = []
    for strategy in registry.strategies:
        live = live_by_id.get(strategy.id, {})
        baseline_values = strategy.baselines.model_dump(exclude_none=True)
        backtest_state = "PENDING_STEP_16" if baseline_values else "NO_BASELINE"
        strategies.append({
            "strategy_id": strategy.id,
            "portfolio_id": strategy.portfolio_id,
            "live_metrics": live.get("metrics"),
            "backtest_state": backtest_state,
            "regime_state": "PENDING_STEP_17",
            "ehi": None,
            "status": "NO_BASELINE" if not baseline_values else "PENDING_ANALYSIS",
            "note": "Sin baseline verificable; no se calcula EHI." if not baseline_values else "Los cálculos comparativos llegan en los pasos 16–19.",
        })
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return {
        "week": week,
        "generated_at": timestamp,
        "source": source.get("source", "fixture"),
        "market_data_warning": "Sin clasificador de régimen hasta completar el Paso 17.",
        "strategies": strategies,
        "worst_ehi": None,
        "status": "PENDING_ANALYSIS",
    }


def write_artifacts(summary: dict[str, Any], output_root: Path) -> Path:
    week_dir = output_root / summary["week"]
    week_dir.mkdir(parents=True, exist_ok=True)
    (week_dir / "charts").mkdir(exist_ok=True)
    (week_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (week_dir / "charts" / "README.md").write_text(
        "Charts are intentionally deferred until the deterministic EHI and market-regime calculations in Steps 16–19 exist.\n"
    )
    backtest = {
        "week": summary["week"],
        "strategies": [{"strategy_id": row["strategy_id"], "status": row["backtest_state"], "verdict": None} for row in summary["strategies"]],
    }
    regime = {
        "week": summary["week"],
        "strategies": [{"strategy_id": row["strategy_id"], "status": row["regime_state"], "verdict": None} for row in summary["strategies"]],
    }
    (week_dir / "check_vs_backtest.json").write_text(json.dumps(backtest, indent=2) + "\n")
    (week_dir / "check_regime.json").write_text(json.dumps(regime, indent=2) + "\n")
    with (week_dir / "ehi.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["strategy_id", "ehi", "band", "status"])
        writer.writeheader()
        for row in summary["strategies"]:
            writer.writerow({"strategy_id": row["strategy_id"], "ehi": "", "band": "N/A", "status": row["status"]})
    status_lines = "\n".join(f"- [ ] {row['strategy_id']}: backtest `{row['backtest_state']}`, régimen `{row['regime_state']}`, EHI pendiente." for row in summary["strategies"])
    (week_dir / "sop_checklist.md").write_text(
        f"# Checklist SOP semanal — {summary['week']}\n\n"
        "Resultados pendientes de los pasos 16–19; sin veredicto ni EHI hasta disponer de cálculos y fuentes verificables.\n\n"
        f"{status_lines}\n\n- [ ] Revisión humana y decisión registrada en `reports/decisions.csv`.\n"
    )
    report_lines = [
        f"# Revisión semanal — {summary['week']}", "",
        f"Estado: `{summary['status']}`. No hay EHI calculado.", "",
        "Los baselines permanecen ausentes y la comparación de régimen se implementa en el Paso 17. Este reporte no es una recomendación de trading.", "",
        "| Estrategia | Estado backtest | Estado régimen | EHI |", "|---|---|---|---:|",
    ]
    report_lines.extend(f"| {row['strategy_id']} | {row['backtest_state']} | {row['regime_state']} | — |" for row in summary["strategies"])
    report_lines.extend(["", "Fuente de mercado de referencia y advertencia CFD se añadirán con el Paso 17."])
    (week_dir / "report.md").write_text("\n".join(report_lines) + "\n")
    return week_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the idempotent weekly review artifacts.")
    parser.add_argument("--week", default="auto")
    parser.add_argument("--fixture", type=Path, help="offline fixture for workflow_dispatch validation")
    parser.add_argument("--output-root", type=Path, default=Path("reports/weekly"))
    args = parser.parse_args(argv)
    try:
        week = iso_week(args.week)
        if args.fixture:
            source = json.loads(args.fixture.read_text())
            source["source"] = "simulator_fixture"
        else:
            api_url = os.getenv("MONITOR_API_URL")
            token = os.getenv("MONITOR_API_TOKEN")
            if not api_url or not token:
                parser.error("set MONITOR_API_URL and MONITOR_API_TOKEN, or pass --fixture")
            source = _fetch_live(api_url, token)
        summary = build_summary(week, source)
        folder = write_artifacts(summary, args.output_root)
        print(json.dumps({"week": week, "output": str(folder), "status": summary["status"]}))
    except (OSError, ValueError, requests.RequestException) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
