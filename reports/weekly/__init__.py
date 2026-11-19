"""Weekly review artifact generation; later steps add deterministic checks."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from app.monitoring.strategies import load_registry
from .backtest import strategy_backtest_analysis
from .ehi import load_ehi_config, render_ehi_history, score_ehi
from .regime import build_regime_report, render_regime_heatmaps

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
        portfolio = detail.json()
        for strategy in portfolio.get("strategies", []):
            strategy_id = strategy["id"]
            trades = []
            offset = 0
            while True:
                response = session.get(
                    f"{api_url.rstrip('/')}/strategies/{strategy_id}/trades?limit=1000&offset={offset}",
                    timeout=30,
                )
                response.raise_for_status()
                trade_page = response.json()
                items = trade_page.get("items", [])
                trades.extend(items)
                if not items or len(trades) >= (trade_page.get("total") or len(trades)):
                    break
                offset += len(items)
            strategy["trades"] = trades
            equity_samples = []
            offset = 0
            while True:
                samples_response = session.get(
                    f"{api_url.rstrip('/')}/strategies/{strategy_id}/equity?limit=2000&offset={offset}",
                    timeout=30,
                )
                samples_response.raise_for_status()
                sample_page = samples_response.json()
                items = sample_page.get("items", [])
                equity_samples.extend(items)
                if not items or len(equity_samples) >= (sample_page.get("total") or len(equity_samples)):
                    break
                offset += len(items)
            strategy["equity_samples"] = equity_samples
        portfolios.append(portfolio)
    return {"portfolios": portfolios, "source": "monitor_api"}


def build_summary(
    week: str,
    source: dict[str, Any],
    *,
    now: datetime | None = None,
    backtest_dir: Path = Path("data/backtests"),
    reconciliation_file: Path | None = None,
    market_downloader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    live_by_id = {}
    for portfolio in source.get("portfolios", []):
        for strategy in portfolio.get("strategies", []):
            live_by_id[strategy.get("id", "")] = strategy

    regime_options = {
        "backtest_dir": backtest_dir,
        "market_data_enabled": source.get("source") != "simulator_fixture",
    }
    if market_downloader is not None:
        regime_options["downloader"] = market_downloader
    regime_report = build_regime_report(week, source, **regime_options)
    regime_by_id = {row["strategy_id"]: row for row in regime_report["strategies"]}
    ehi_config = load_ehi_config()

    strategies = []
    for strategy in registry.strategies:
        live = live_by_id.get(strategy.id, {})
        analysis = strategy_backtest_analysis(
            strategy.id,
            live.get("trades", []),
            backtest_dir / f"{strategy.id}.csv",
            recon_file=reconciliation_file,
            week_seed=week,
        )
        regime_analysis = regime_by_id.get(strategy.id, {"status": "UNCONFIGURED", "verdict": None})
        ehi = score_ehi(analysis, regime_analysis, ehi_config)
        backtest_state = analysis["status"]
        strategies.append({
            "strategy_id": strategy.id,
            "portfolio_id": strategy.portfolio_id,
            "expected_mode": strategy.expected_mode,
            "current_mode": live.get("current_mode"),
            "mode_status": live.get("mode_status", "unconfirmed"),
            "mode_observed_at": live.get("mode_observed_at"),
            "live_metrics": analysis["live_metrics"],
            "backtest_analysis": analysis,
            "backtest_state": backtest_state,
            "regime_state": regime_analysis["status"],
            "regime_analysis": regime_analysis,
            "ehi": ehi["ehi"],
            "ehi_band": ehi["band"],
            "ehi_status": ehi["status"],
            "ehi_components": ehi["components"],
            "ehi_component_states": ehi["component_states"],
            "status": "NO_BASELINE" if backtest_state == "NO_BASELINE" else backtest_state,
            "note": "Sin CSV de backtest verificable; se reportan métricas live sin veredicto." if backtest_state == "NO_BASELINE" else "EHI provisional; ponderaciones y bandas documentadas en config/ehi.yaml.",
        })
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return {
        "week": week,
        "generated_at": timestamp,
        "source": source.get("source", "fixture"),
        "market_data_warning": regime_report["market_data_note"],
        "regime_report": regime_report,
        "strategies": strategies,
        "worst_ehi": min((row["ehi"] for row in strategies if row["ehi"] is not None), default=None),
        "status": "PENDING_ANALYSIS",
    }


def write_artifacts(summary: dict[str, Any], output_root: Path) -> Path:
    week_dir = output_root / summary["week"]
    week_dir.mkdir(parents=True, exist_ok=True)
    (week_dir / "charts").mkdir(exist_ok=True)
    (week_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (week_dir / "charts" / "README.md").write_text(
        "Charts are rendered only when their required live, backtest, market, or historical EHI data are available. EHI scores are provisional; see report.md and config/ehi.yaml.\n"
    )
    backtest = {
        "week": summary["week"],
        "strategies": [{
            "strategy_id": row["strategy_id"],
            "status": row["backtest_state"],
            "verdict": row["backtest_analysis"].get("windows", {}).get("last_50_trades", {}).get("verdict"),
            "analysis": row["backtest_analysis"],
        } for row in summary["strategies"]],
    }
    regime = {
        "week": summary["week"],
        "market_data_note": summary.get("market_data_warning", "Market context unavailable."),
        "strategies": [{
            "strategy_id": row["strategy_id"],
            "status": row["regime_state"],
            "verdict": row["regime_analysis"].get("verdict"),
            "analysis": row["regime_analysis"],
        } for row in summary["strategies"]],
    }
    (week_dir / "check_vs_backtest.json").write_text(json.dumps(backtest, indent=2) + "\n")
    (week_dir / "check_regime.json").write_text(json.dumps(regime, indent=2) + "\n")
    unavailable_states = {"NO_BASELINE", "INSUFFICIENT_DATA", "INVALID_BASELINE", "MARKET_DATA_UNAVAILABLE", "SIMULATOR_NO_MARKET_DATA", "UNCONFIGURED"}
    review_rows = []
    for row in summary["strategies"]:
        comparison = row.get("backtest_analysis", {}).get("windows", {}).get("last_50_trades", {})
        reconciliation = row.get("backtest_analysis", {}).get("reconciliation", {})
        regime_row = row.get("regime_analysis", {})
        signals = []
        if comparison.get("verdict") == "OUTSIDE_BOOTSTRAP_90":
            signals.append("BACKTEST_OUTSIDE_BOOTSTRAP_90")
        if row.get("ehi_band") == "RED":
            signals.append("EHI_RED")
        if regime_row.get("status") == "ADVERSE_HYPOTHESIS":
            signals.append("ADVERSE_REGIME_HYPOTHESIS" if not regime_row.get("hypothesis_confirmed") else "CONFIRMED_ADVERSE_REGIME")
        if reconciliation.get("mismatches"):
            signals.append("TRADE_RECONCILIATION_MISMATCH")
        if row.get("mode_status") == "mode_mismatch":
            signals.append("ACCOUNT_MODE_MISMATCH")
        limitations = []
        if row.get("backtest_state") in unavailable_states:
            limitations.append(row["backtest_state"])
        if row.get("regime_state") in unavailable_states:
            limitations.append(row["regime_state"])
        if row.get("ehi") is None:
            limitations.append(row.get("ehi_status", "EHI_UNAVAILABLE"))
        if signals:
            state = "REVIEW_REQUIRED"
        elif limitations:
            state = "NO_VERDICT_DATA_LIMITED"
        else:
            state = "READY_FOR_HUMAN_REVIEW"
        review_rows.append({"strategy_id": row["strategy_id"], "state": state, "signals": signals, "limitations": sorted(set(limitations)), "ehi": row.get("ehi"), "ehi_band": row.get("ehi_band", "N/A"), "backtest_verdict": comparison.get("verdict"), "regime_status": regime_row.get("status"), "regime_hypothesis_confirmed": regime_row.get("hypothesis_confirmed", False), "reconciliation_status": reconciliation.get("status")})
    summary["review"] = {"status": "REVIEW_REQUIRED" if any(row["state"] == "REVIEW_REQUIRED" for row in review_rows) else "DATA_LIMITED" if any(row["state"] == "NO_VERDICT_DATA_LIMITED" for row in review_rows) else "READY_FOR_HUMAN_REVIEW", "strategies": review_rows}
    (week_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (week_dir / "check_vs_backtest.json").write_text(json.dumps({**backtest, "review": [{"strategy_id": row["strategy_id"], "state": row["state"], "signals": row["signals"], "verdict": row["backtest_verdict"], "ehi": row["ehi"], "ehi_band": row["ehi_band"]} for row in review_rows]}, indent=2) + "\n")
    (week_dir / "check_regime.json").write_text(json.dumps({**regime, "review": [{"strategy_id": row["strategy_id"], "state": row["state"], "regime_status": row["regime_status"], "hypothesis_confirmed": row["regime_hypothesis_confirmed"], "ehi": row["ehi"], "ehi_band": row["ehi_band"]} for row in review_rows]}, indent=2) + "\n")
    if any(row["backtest_analysis"].get("cone") for row in summary["strategies"]):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for row in summary["strategies"]:
            cone = row["backtest_analysis"].get("cone")
            if not cone:
                continue
            x = cone["trade_index"]
            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.fill_between(x, cone["bands"]["p5"], cone["bands"]["p95"], alpha=0.14, label="P5–P95 backtest")
            ax.fill_between(x, cone["bands"]["p25"], cone["bands"]["p75"], alpha=0.24, label="P25–P75 backtest")
            ax.plot(x, cone["bands"]["p50"], label="P50 backtest")
            ax.plot(x, cone["live_equity_index"], label="Live", linewidth=2)
            ax.set(title=f"{row['strategy_id']} — equity cone", xlabel="Trade number", ylabel="Equity index (start = 1)")
            ax.legend()
            fig.tight_layout()
            fig.savefig(week_dir / "charts" / f"{row['strategy_id']}_cone.png", dpi=140)
            plt.close(fig)
    render_regime_heatmaps(summary.get("regime_report", {}), week_dir / "charts")
    history_charts = render_ehi_history(summary["week"], summary["strategies"], output_root)
    with (week_dir / "ehi.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["week", "portfolio_id", "strategy_id", "expected_mode", "current_mode", "mode_status", "mode_observed_at", "ehi", "band", "status", "backtest_component", "regime_component", "backtest_state", "regime_component_state"])
        writer.writeheader()
        for row in summary["strategies"]:
            components = row.get("ehi_components", {})
            component_states = row.get("ehi_component_states", {})
            writer.writerow({"week": summary["week"], "portfolio_id": row.get("portfolio_id"), "strategy_id": row["strategy_id"], "expected_mode": row.get("expected_mode"), "current_mode": row.get("current_mode"), "mode_status": row.get("mode_status", "unconfirmed"), "mode_observed_at": row.get("mode_observed_at"), "ehi": row.get("ehi") if row.get("ehi") is not None else "", "band": row.get("ehi_band", "N/A"), "status": row.get("ehi_status", "NOT_CALCULATED"), "backtest_component": components.get("backtest_percentile"), "regime_component": components.get("regime_score"), "backtest_state": row["backtest_state"], "regime_component_state": component_states.get("regime", "NOT_CALCULATED")})
    review_by_id = {row["strategy_id"]: row for row in review_rows}
    status_lines = "\n".join(
        f"- [ ] **{row['strategy_id']}** — `{review_by_id[row['strategy_id']]['state']}`; backtest `{row['backtest_state']}`; régimen `{row['regime_state']}`; EHI `{row.get('ehi') if row.get('ehi') is not None else 'N/D'}` ({row.get('ehi_band', 'N/A')}). "
        f"Señales: {', '.join(review_by_id[row['strategy_id']]['signals']) or 'ninguna'}. "
        f"Limitaciones: {', '.join(review_by_id[row['strategy_id']]['limitations']) or 'ninguna'}"
        for row in summary["strategies"]
    )
    (week_dir / "sop_checklist.md").write_text(
        f"# Checklist SOP semanal — {summary['week']}\n\n"
        f"Estado general: `{summary['review']['status']}`. Consulta [informe](report.md), [live vs backtest](check_vs_backtest.json) y [régimen](check_regime.json).\n\n"
        "El EHI es provisional; las hipótesis no confirmadas no generan una conclusión direccional. Las limitaciones de datos no son veredictos.\n\n"
        f"{status_lines}\n\n- [ ] Revisar discrepancias EA/motor y costes de ejecución.\n- [ ] Aprobar o descartar señales con contexto y registrar la decisión humana en `reports/decisions.csv` (sin completar automáticamente).\n"
    )
    report_lines = [
        f"# Revisión semanal — {summary['week']}", "",
        f"Estado: `{summary['review']['status']}`. Se requiere revisión humana; no es una recomendación de trading.", "",
        "## Resumen ejecutivo", "",
        f"- Estrategias revisadas: {len(review_rows)}; alertas de revisión: {sum(row['state'] == 'REVIEW_REQUIRED' for row in review_rows)}; limitadas por datos: {sum(row['state'] == 'NO_VERDICT_DATA_LIMITED' for row in review_rows)}.",
        f"- EHI más bajo disponible: {summary.get('worst_ehi') if summary.get('worst_ehi') is not None else 'N/D'}; scores provisionales y ponderaciones en `config/ehi.yaml`.",
        f"- {summary.get('market_data_warning', 'Contexto de mercado no disponible.')}",
        "- Interpretar bootstrap, régimen, reconciliación y EHI conjuntamente; ninguna regla modifica operaciones.", "",
        f"Las comparaciones live/backtest usan bootstrap por bloques cuando existe CSV y n≥20. {summary.get('market_data_warning', 'Market context unavailable.')} Este reporte no es una recomendación de trading.", "",
        "| Portfolio | Estrategia | Modo observado / esperado | Revisión | Estado backtest | Régimen | Lectura actual | EHI | Señales |", "|---|---|---|---|---|---|---|---:|---|",
    ]
    def regime_label(row):
        current = row["regime_analysis"].get("current_regime")
        if not current:
            return "—"
        return f"{current['trend']} {current['direction']}; vol {current['volatility']}; close {current['price']} SMA200"

    report_lines.extend(
        f"| {row.get('portfolio_id', '—')} | {row['strategy_id']} | {row.get('current_mode') or 'Sin confirmar'} / {row.get('expected_mode', '—')} | {review_by_id[row['strategy_id']]['state']} | {row['backtest_state']} | {row['regime_state']}{' (hipótesis no confirmada)' if row['regime_analysis'].get('status') == 'ADVERSE_HYPOTHESIS' and not row['regime_analysis'].get('hypothesis_confirmed') else ''} | {regime_label(row)} | {row.get('ehi') if row.get('ehi') is not None else 'N/D'} ({row.get('ehi_band', 'N/A')}) | {', '.join(review_by_id[row['strategy_id']]['signals']) or '—'} |"
        for row in summary["strategies"]
    )
    report_lines.extend(["", "## Límites y referencias", "", "- [Checklist SOP](sop_checklist.md)", "- [Verificación live vs backtest](check_vs_backtest.json)", "- [Verificación de régimen](check_regime.json)", "- Decisiones humanas: `reports/decisions.csv` (registro externo al reporte; no se modifica automáticamente).", "- EHI: promedio ponderado 50/50 de percentiles bootstrap (expectancy, profit factor, win rate) y componente de régimen; bandas provisionalmente rojo <30, ámbar 30–69, verde ≥70. Hipótesis de régimen no confirmadas usan neutral 50.", "- Los datos de referencia de Yahoo Finance pueden diferir del CFD del broker; las hipótesis permanecen sin confirmar hasta su revisión."])
    (week_dir / "report.md").write_text("\n".join(report_lines) + "\n")
    from .email import render_sop_email
    (week_dir / "sop_email.html").write_text(
        render_sop_email(summary, dashboard_url=os.getenv("WEEKLY_DASHBOARD_URL")), encoding="utf-8",
    )
    return week_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the idempotent weekly review artifacts.")
    parser.add_argument("--week", default="auto")
    parser.add_argument("--fixture", type=Path, help="offline fixture for workflow_dispatch validation")
    parser.add_argument("--output-root", type=Path, default=Path("reports/weekly"))
    parser.add_argument("--backtests-dir", type=Path, default=Path("data/backtests"))
    parser.add_argument("--reconciliation-file", type=Path)
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
        summary = build_summary(
            week,
            source,
            backtest_dir=args.backtests_dir,
            reconciliation_file=args.reconciliation_file,
        )
        folder = write_artifacts(summary, args.output_root)
        print(json.dumps({"week": week, "output": str(folder), "status": summary["status"]}))
    except (OSError, ValueError, requests.RequestException) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
