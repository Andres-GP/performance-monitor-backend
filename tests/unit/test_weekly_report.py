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
    assert "EHI provisional" in (first_dir / "report.md").read_text()


def test_workflow_dispatch_contract_has_manual_fixture_path():
    import yaml

    workflow = yaml.load(Path(".github/workflows/weekly_review.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"][0]["cron"] == "0 6 * * 1"
    assert "workflow_dispatch" in workflow["on"]
