"""Branded weekly SOP email rendering and optional Resend delivery."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

RECIPIENT = "andresgarciapedreros@gmail.com"
FOREST = "#1f3d36"
PANEL = "#2b4d44"
LIME = "#c8f5a8"
SAGE = "#adc5b7"


def _safe(value: Any, fallback: str = "—") -> str:
    return html.escape(str(value)) if value not in (None, "") else fallback


def _mode_label(row: dict[str, Any]) -> str:
    expected = row.get("expected_mode")
    current = row.get("current_mode")
    if current in {"demo", "live"}:
        label = "Demo" if current == "demo" else "Capital real"
        if expected in {"demo", "live"} and current != expected:
            return f"{label} · no coincide con lo esperado ({expected})"
        return label
    expected_label = "Demo" if expected == "demo" else "Capital real" if expected == "live" else "desconocido"
    return f"Sin confirmar · esperado: {expected_label}"


def render_sop_email(summary: dict[str, Any], *, dashboard_url: str | None = None) -> str:
    review = summary.get("review", {})
    review_by_id = {row.get("strategy_id"): row for row in review.get("strategies", [])}
    rows = []
    for strategy in summary.get("strategies", []):
        strategy_id = _safe(strategy.get("strategy_id"))
        verdict = review_by_id.get(strategy.get("strategy_id"), {})
        ehi = strategy.get("ehi")
        ehi_label = "Sin datos" if ehi is None else f"{float(ehi):.1f} / 100 · {_safe(strategy.get('ehi_band', 'N/A'))}"
        mode = _mode_label(strategy)
        if strategy.get("mode_observed_at"):
            mode += f"<br><span style='color:#8fa99a;font-size:10px'>observado {_safe(strategy['mode_observed_at'])}</span>"
        status = verdict.get("state", strategy.get("status", "—"))
        color = "#f2c879" if status == "REVIEW_REQUIRED" else LIME if status == "READY_FOR_HUMAN_REVIEW" else SAGE
        rows.append(
            "<tr>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:{SAGE}'>{_safe(strategy.get('portfolio_id'))}</td>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:#f2f5ef;font-weight:600'>{strategy_id}</td>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:#d7e4db'>{mode}</td>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:#d7e4db'>{_safe(strategy.get('backtest_state'))}</td>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:#d7e4db'>{ehi_label}</td>"
            f"<td style='padding:14px 12px;border-bottom:1px solid #426257;color:{color};font-weight:600'>{_safe(status)}</td>"
            "</tr>"
        )
    signals = []
    for row in review.get("strategies", []):
        for signal in row.get("signals", []):
            signals.append(f"<li style='padding:5px 0;color:#d7e4db'><b>{_safe(row.get('strategy_id'))}</b> · {_safe(signal)}</li>")
    issues = "".join(signals) or "<li style='padding:5px 0;color:#adc5b7'>Sin señales automáticas de revisión esta semana.</li>"
    checklist_items = []
    for row in review.get("strategies", []):
        signals_text = ", ".join(row.get("signals", [])) or "sin señales automáticas"
        limits_text = ", ".join(row.get("limitations", [])) or "sin limitaciones registradas"
        checklist_items.append(
            f"<li style='padding:7px 0;color:#d7e4db'><span style='color:{LIME}'>□</span> <b>{_safe(row.get('strategy_id'))}</b> · {_safe(row.get('state'))}"
            f"<br><span style='padding-left:19px;color:#9fb7a8;font-size:11px'>Señales: {_safe(signals_text)} · Datos: {_safe(limits_text)}</span></li>"
        )
    checklist = "".join(checklist_items) or "<li style='padding:7px 0;color:#adc5b7'>No hay estrategias para revisar.</li>"
    link = (f"<a href='{html.escape(dashboard_url, quote=True)}' style='color:{LIME};text-decoration:none'>Abrir dashboard semanal →</a>"
            if dashboard_url else "")
    week = _safe(summary.get("week"))
    status = _safe(review.get("status", summary.get("status", "PENDING_ANALYSIS")))
    worst_ehi = summary.get("worst_ehi")
    ehi_value = "Sin baseline disponible" if worst_ehi is None else f"{float(worst_ehi):.1f} / 100"
    market_note = _safe(summary.get("market_data_warning"), "Contexto de mercado no disponible.")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 10px;background:{FOREST};font-family:Arial,Helvetica,sans-serif;color:#f2f5ef">
<div style="max-width:780px;margin:0 auto;border:1px solid #49685d;border-radius:18px;overflow:hidden;background:{PANEL}">
  <div style="height:5px;background:{LIME}"></div>
  <header style="padding:30px 32px 24px;background:linear-gradient(135deg,{FOREST},{PANEL})">
    <p style="margin:0 0 18px;color:{LIME};font-size:11px;letter-spacing:2px;font-weight:bold">ALPHACA CAPITAL <span style="color:{SAGE}">/ PERFORMANCE MONITOR</span></p>
    <p style="margin:0 0 8px;color:{SAGE};font-size:11px;letter-spacing:1.5px;text-transform:uppercase">SOP · revisión semanal</p>
    <h1 style="margin:0;font-size:30px;line-height:1.2;letter-spacing:-1px;color:#f2f5ef">Estado de estrategias y portfolio</h1>
    <p style="margin:12px 0 0;color:#c4d5ca;font-size:14px">Semana ISO <b style="color:{LIME}">{week}</b></p>
  </header>
  <main style="padding:0 32px 30px">
    <table role="presentation" style="width:100%;border-collapse:separate;border-spacing:10px 0;margin:8px 0 26px"><tr>
      <td style="width:50%;padding:16px;border:1px solid #426257;border-radius:12px;background:{FOREST}"><span style="display:block;color:{SAGE};font-size:11px">Estado general</span><strong style="display:block;margin-top:8px;color:{LIME};font-size:16px">{status}</strong></td>
      <td style="width:50%;padding:16px;border:1px solid #426257;border-radius:12px;background:{FOREST}"><span style="display:block;color:{SAGE};font-size:11px">EHI más bajo disponible</span><strong style="display:block;margin-top:8px;color:#f2f5ef;font-size:16px">{_safe(ehi_value)}</strong></td>
    </tr></table>
    <h2 style="margin:0 0 10px;color:#f2f5ef;font-size:17px">Estrategias por portfolio</h2>
    <p style="margin:0 0 14px;color:{SAGE};font-size:12px;line-height:1.6">El modo operativo muestra el último modo observado; cuando falta evidencia se indica el modo esperado como referencia.</p>
    <div style="overflow-x:auto;border:1px solid #426257;border-radius:12px">
      <table style="width:100%;min-width:600px;border-collapse:collapse;text-align:left;font-size:12px">
        <thead><tr style="background:{FOREST};color:{SAGE}"><th style="padding:12px">Portfolio</th><th style="padding:12px">Estrategia</th><th style="padding:12px">Demo / capital</th><th style="padding:12px">Backtest</th><th style="padding:12px">EHI</th><th style="padding:12px">Revisión SOP</th></tr></thead>
        <tbody>{''.join(rows) or '<tr><td colspan="6" style="padding:16px;color:#adc5b7">Sin estrategias en el resumen.</td></tr>'}</tbody>
      </table>
    </div>
    <h2 style="margin:26px 0 8px;color:#f2f5ef;font-size:17px">Puntos a revisar</h2>
    <ul style="margin:0;padding-left:18px">{issues}</ul>
    <h2 style="margin:26px 0 8px;color:#f2f5ef;font-size:17px">Checklist SOP</h2>
    <ul style="margin:0;padding-left:18px;list-style:none">{checklist}</ul>
    <p style="margin:14px 0 0;color:{SAGE};font-size:12px;line-height:1.7">Revisar discrepancias EA/motor y costos de ejecución; contrastar live con backtest y régimen; registrar la decisión humana en reports/decisions.csv. Esta revisión no cambia operaciones.</p>
    <div style="margin-top:22px;padding:16px;border-left:2px solid {LIME};background:{FOREST};color:{SAGE};font-size:12px;line-height:1.7">
      <b style="color:#f2f5ef">Contexto y límites</b><br>{market_note}<br>El EHI es provisional. Las hipótesis de régimen no confirmadas usan un componente neutral. Este mensaje apoya la revisión SOP; no modifica operaciones ni sustituye la validación humana.
    </div>
    <p style="margin:22px 0 0;font-size:13px">{link}</p>
  </main>
  <footer style="padding:16px 32px;border-top:1px solid #426257;color:#8fa99a;font-size:10px;letter-spacing:.4px">ALPHACA CAPITAL · INTERNAL WEEKLY OPERATIONS REVIEW</footer>
</div></body></html>"""


def send_sop_email(html_body: str, *, api_key: str, from_email: str, recipient: str = RECIPIENT, subject: str) -> dict[str, Any]:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": from_email, "to": [recipient], "subject": subject, "html": html_body},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send the generated weekly SOP email through Resend.")
    parser.add_argument("--week", required=True)
    parser.add_argument("--reports-root", type=Path, default=Path("reports/weekly"))
    args = parser.parse_args(argv)
    key = os.getenv("RESEND_API_KEY")
    if not key:
        print("RESEND_API_KEY is not configured; weekly SOP email skipped.", file=sys.stderr)
        return 0
    email_path = args.reports_root / args.week / "sop_email.html"
    summary_path = args.reports_root / args.week / "summary.json"
    if not email_path.exists() or not summary_path.exists():
        parser.error(f"weekly SOP artifacts are missing for {args.week}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    week = summary.get("week", args.week)
    try:
        result = send_sop_email(
            email_path.read_text(encoding="utf-8"), api_key=key,
            from_email=os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
            recipient=os.getenv("SOP_EMAIL_TO", RECIPIENT),
            subject=f"Alphaca Capital | SOP semanal {week}",
        )
    except requests.RequestException as exc:
        parser.error(f"Resend could not deliver weekly SOP email: {exc}")
    print(json.dumps({"week": week, "recipient": os.getenv("SOP_EMAIL_TO", RECIPIENT), "email_id": result.get("id")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
