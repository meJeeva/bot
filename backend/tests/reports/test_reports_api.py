"""Read-only report endpoint contracts.

The reports are plain files written by the historical-simulation CLI, so these
tests build a temporary reports directory by hand and assert that the API lists,
reads and serves them without ever escaping the configured root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fakes import gold_terminal_with_live_tick


def _client(make_settings, reports_dir: Path, **overrides) -> TestClient:
    from app.main import create_app

    overrides.setdefault("poll_interval_ms", 200)
    overrides["reports_dir"] = str(reports_dir)
    app = create_app(make_settings(**overrides), mt5_module=gold_terminal_with_live_tick())
    return TestClient(app)


def _write_run(reports_dir: Path, run_id: str, *, comparison: bool = False) -> Path:
    run_dir = reports_dir / run_id
    run_dir.mkdir(parents=True)
    if comparison:
        summary_name = "comparison_summary.json"
        summary = {
            "report_type": "fibonacci_exit_policy_comparison",
            "run_id": run_id,
            "generated_at_utc": "2026-10-14T04:44:38.965474+00:00",
            "symbol": "XAUUSD",
            "requested_start_utc": "2026-04-14T00:00:00+00:00",
            "requested_end_utc": "2026-10-14T04:44:38.965474+00:00",
            "timeframes": ["M1", "M5", "M15"],
            "scenarios": [{"scenario": "baseline"}],
        }
        (run_dir / "cost_sensitivity.csv").write_text("cost,net\n0.46,-1\n", encoding="utf-8")
    else:
        summary_name = "summary.json"
        summary = {
            "report_type": "fibonacci_xauusd_backtest",
            "run_id": run_id,
            "generated_at_utc": "2026-10-14T04:07:35.735519+00:00",
            "generated_at_ist": "2026-10-14T09:37:35.735519+05:30",
            "symbol_requested": "XAUUSD",
            "symbol_resolved": "XAUUSD",
            "requested_start_utc": "2026-04-14T00:00:00+00:00",
            "requested_end_utc": "2026-10-14T04:07:35.735519+00:00",
            "timeframes_requested": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
            "timeframe_count": 7,
            "strategy_fingerprint": "4eea76386812",
        }
        (run_dir / "M15.csv").write_text("time,close\n1,2\n", encoding="utf-8")
    (run_dir / summary_name).write_text(json.dumps(summary), encoding="utf-8")
    return run_dir


class TestReports:
    def test_lists_runs_newest_first_with_provenance(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")
        _write_run(reports, "exit_compare_new_70ab4988", comparison=True)

        with _client(make_settings, reports) as client:
            response = client.get("/api/reports")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is True
        assert body["count"] == 2
        assert body["read_only"] is True
        assert body["trading_enabled"] is False
        assert body["reports_root"] == str(reports)

        run_ids = [run["run_id"] for run in body["runs"]]
        assert set(run_ids) == {"xauusd_old_4eea7638", "exit_compare_new_70ab4988"}
        # Newest by generated time first.
        assert run_ids[0] == "exit_compare_new_70ab4988"

        by_id = {run["run_id"]: run for run in body["runs"]}
        run = by_id["xauusd_old_4eea7638"]
        assert run["report_type"] == "fibonacci_xauusd_backtest"
        assert run["symbol"] == "XAUUSD"
        assert run["timeframe_count"] == 7
        assert run["summary_available"] is True
        assert "summary.json" in run["files"]
        assert "M15.csv" in run["files"]

    def test_reports_missing_directory_as_unavailable(self, make_settings, tmp_path):
        missing = tmp_path / "does-not-exist"

        with _client(make_settings, missing) as client:
            response = client.get("/api/reports")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["count"] == 0
        assert body["runs"] == []

    def test_returns_one_run_with_parsed_summary(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        with _client(make_settings, reports) as client:
            response = client.get("/api/reports/xauusd_old_4eea7638")

        assert response.status_code == 200
        body = response.json()
        assert body["summary_file"] == "summary.json"
        assert body["summary"]["strategy_fingerprint"] == "4eea76386812"

    def test_unknown_run_is_404(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        with _client(make_settings, reports) as client:
            response = client.get("/api/reports/nope")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "report_not_found"

    def test_downloads_an_artifact(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        with _client(make_settings, reports) as client:
            response = client.get("/api/reports/xauusd_old_4eea7638/files/M15.csv")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "time,close" in response.text

    def test_missing_artifact_is_404(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        with _client(make_settings, reports) as client:
            response = client.get("/api/reports/xauusd_old_4eea7638/files/secret.txt")

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "run_id",
        ["%2e%2e", "a/b"],
    )
    def test_rejects_path_traversal_in_run_id(self, make_settings, tmp_path, run_id):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        with _client(make_settings, reports) as client:
            response = client.get(f"/api/reports/{run_id}")

        # Either the router does not match (404) or the service rejects it
        # (400/404); in no case does it read outside the reports root.
        assert response.status_code in (400, 404)

    def test_service_rejects_dot_segments(self, tmp_path):
        """The path-confinement rule rejects ``..`` regardless of routing."""
        from app.reports.service import ReportError, load_run, read_artifact

        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")

        for bad in ("..", "../..", "xauusd_old_4eea7638/.."):
            with pytest.raises(ReportError):
                load_run(reports, bad)
        with pytest.raises(ReportError):
            read_artifact(reports, "xauusd_old_4eea7638", "../secret.txt")

    def test_rejects_path_traversal_in_filename(self, make_settings, tmp_path):
        reports = tmp_path / "reports"
        _write_run(reports, "xauusd_old_4eea7638")
        secret = reports / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")

        with _client(make_settings, reports) as client:
            response = client.get(
                "/api/reports/xauusd_old_4eea7638/files/..%2fsecret.txt"
            )

        assert response.status_code in (400, 404)
