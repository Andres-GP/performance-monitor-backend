import csv
import json
from pathlib import Path

import pytest

from reports.weekly import build_summary, iso_week, main, write_artifacts


def test_iso_week_validates_and_normalizes():
    assert iso_week("2026-W7") == "2026-W07"
    with pytest.raises(ValueError):
        iso_week("2026-W99")


def test_fixture_weekly_report_is_honest_and_idempotent(tmp_path):
    fixture = Path("reports/fixtures/simulator_week.json")
    assert main(["--week", "2026-W47", "--fixture", str(fixture), "--output-root", str(tmp_path), "--backtests-dir", str(tmp_path / "backtests")]) == 0
    first_dir = tmp_path / "2026-W47"
    first_summary = json.loads((first_dir / "summary.json").read_text())
    assert first_summary["source"] == "simulator_fixture"
    assert len(first_summary["strategies"]) == 5
    assert all(item["ehi"] is None for item in first_summary["strategies"])
    assert all(item["backtest_state"] == "NO_BASELINE" for item in first_summary["strategies"])
    assert main(["--week", "2026-W47", "--fixture", str(fixture), "--output-root", str(tmp_path), "--backtests-dir", str(tmp_path / "backtests")]) == 0
    assert list(tmp_path.iterdir()) == [first_dir]
    with (first_dir / "ehi.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 5
    assert "no EHI" not in (first_dir / "report.md").read_text()
    assert "El EHI es provisional" in (first_dir / "sop_checklist.md").read_text()


def test_workflow_dispatch_contract_has_manual_fixture_path():
    import yaml

    workflow = yaml.load(Path(".github/workflows/weekly_review.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"][0]["cron"] == "0 6 * * 1"
    assert "workflow_dispatch" in workflow["on"]
    workflow_text = Path(".github/workflows/weekly_review.yml").read_text()
    assert "Send weekly SOP email" in workflow_text
    assert "SOP_EMAIL_TO: andresgarciapedreros@gmail.com" in workflow_text


def test_step19_combines_checks_without_writing_human_decisions(tmp_path):
    before = Path("reports/decisions.csv").read_bytes()
    strategy = {
        "strategy_id": "STRAT", "backtest_state": "COMPARED", "regime_state": "ADVERSE_HYPOTHESIS",
        "ehi": 25, "ehi_band": "RED", "ehi_status": "PROVISIONAL",
        "ehi_components": {"backtest_percentile": 0, "regime_score": 50},
        "ehi_component_states": {"regime": "HYPOTHESIS_UNCONFIRMED_NEUTRAL"},
        "backtest_analysis": {"windows": {"last_50_trades": {"verdict": "OUTSIDE_BOOTSTRAP_90"}}, "reconciliation": {"status": "RECONCILED", "mismatches": [{"status": "LIVE_ONLY"}]}},
        "regime_analysis": {"status": "ADVERSE_HYPOTHESIS", "hypothesis_confirmed": False, "current_regime": None},
    }
    summary = {"week": "2026-W47", "generated_at": "2026-11-22T00:00:00+00:00", "source": "test", "status": "PENDING_ANALYSIS", "worst_ehi": 25, "market_data_warning": "market note", "strategies": [strategy]}
    folder = write_artifacts(summary, tmp_path)
    report = (folder / "report.md").read_text()
    checklist = (folder / "sop_checklist.md").read_text()
    checks = json.loads((folder / "check_vs_backtest.json").read_text())
    assert "REVIEW_REQUIRED" in report and "hipótesis no confirmada" in report
    assert "TRADE_RECONCILIATION_MISMATCH" in checklist
    assert checks["review"][0]["state"] == "REVIEW_REQUIRED"
    assert Path("reports/decisions.csv").read_bytes() == before


def test_sop_email_is_branded_and_shows_account_mode():
    from reports.weekly.email import RECIPIENT, render_sop_email

    html = render_sop_email({
        "week": "2026-W47", "worst_ehi": 58.5, "market_data_warning": "Test market note",
        "review": {"status": "DATA_LIMITED", "strategies": [{"strategy_id": "S1", "state": "NO_VERDICT_DATA_LIMITED", "signals": []}]},
        "strategies": [{"portfolio_id": "P_AXI", "strategy_id": "S1", "expected_mode": "demo", "current_mode": "live", "mode_status": "mode_mismatch", "backtest_state": "NO_BASELINE", "ehi": None}],
    })
    assert RECIPIENT == "andresgarciapedreros@gmail.com"
    assert "#1f3d36" in html and "#c8f5a8" in html
    assert "Capital real · no coincide con lo esperado (demo)" in html
    assert "P_AXI" in html and "ALPHACA CAPITAL" in html
    assert "Checklist SOP" in html and "□" in html


def test_sop_email_delivery_uses_requested_recipient(monkeypatch):
    from reports.weekly.email import RECIPIENT, send_sop_email

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"id": "mail-id"}

    captured = {}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("reports.weekly.email.requests.post", fake_post)
    result = send_sop_email("<html></html>", api_key="test-key", from_email="ops@example.com", subject="Weekly SOP")
    assert result["id"] == "mail-id"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["json"]["to"] == [RECIPIENT]
