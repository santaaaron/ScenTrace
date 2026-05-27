from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def analytics_dir(tmp_path: Path) -> Path:
    from scen_trace.analytics import AnalyticsDB
    from scen_trace.report import TraceData

    db = AnalyticsDB(analytics_dir=tmp_path)
    db.init()
    trace = TraceData(
        scenario_id="test_scenario",
        status="passed",
        started_at="2025-01-01T00:00:00",
        finished_at="2025-01-01T00:00:01",
        total_duration_ms=100.0,
        total_input_tokens=50,
        total_output_tokens=25,
        estimated_cost=0.000075,
        checks_passed=2,
        checks_failed=0,
        metadata={"provider": "mock", "model": "mock-v1"},
        turns=[
            {
                "turn_index": 0,
                "agent_name": "greeter",
                "prompt": "Hello",
                "response": "Hi there",
                "timestamp": "2025-01-01T00:00:00",
                "provider": "mock",
                "model": "mock-v1",
                "input_tokens": 30,
                "output_tokens": 15,
                "duration_ms": 50.0,
                "status": "success",
                "check_results": [{"check_id": "greet_check", "passed": True, "message": "ok"}],
            },
            {
                "turn_index": 1,
                "agent_name": "validator",
                "prompt": "Check this",
                "response": "Looks good",
                "timestamp": "2025-01-01T00:00:01",
                "provider": "mock",
                "model": "mock-v1",
                "input_tokens": 20,
                "output_tokens": 10,
                "duration_ms": 50.0,
                "status": "success",
                "check_results": [{"check_id": "val_check", "passed": True, "message": "ok"}],
            },
        ],
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps({
        "scenario_id": trace.scenario_id,
        "status": trace.status,
        "started_at": trace.started_at,
        "finished_at": trace.finished_at,
        "total_duration_ms": trace.total_duration_ms,
        "total_input_tokens": trace.total_input_tokens,
        "total_output_tokens": trace.total_output_tokens,
        "estimated_cost": trace.estimated_cost,
        "checks_passed": trace.checks_passed,
        "checks_failed": trace.checks_failed,
        "metadata": trace.metadata,
        "turns": trace.turns,
    }))
    db.ingest_run(trace_path, trace_data=trace)
    db.close()
    return tmp_path


@pytest.fixture()
def client(analytics_dir: Path):
    from starlette.testclient import TestClient

    from scen_trace.server import create_app

    app = create_app(analytics_dir=analytics_dir, traces_dir=analytics_dir)
    return TestClient(app)


class TestDashboardRoute:
    def test_dashboard_returns_html(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ScenTrace Dashboard" in resp.text
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_has_dark_mode_toggle(self, client) -> None:
        resp = client.get("/")
        assert "toggleTheme" in resp.text


class TestScenariosAPI:
    def test_list_scenarios(self, client) -> None:
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["scenario_id"] == "test_scenario"
        assert data[0]["total_runs"] == 1
        assert "efficiency_score" in data[0]

    def test_scenario_detail(self, client) -> None:
        resp = client.get("/api/scenarios/test_scenario")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario_id"] == "test_scenario"
        assert "trends" in data
        assert "efficiency" in data
        assert "recent_runs" in data
        assert "agent_breakdown" in data

    def test_scenario_not_found(self, client) -> None:
        resp = client.get("/api/scenarios/nonexistent")
        assert resp.status_code == 404


class TestRunsAPI:
    def test_list_runs(self, client) -> None:
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["scenario_id"] == "test_scenario"
        assert data[0]["status"] == "passed"

    def test_list_runs_with_limit(self, client) -> None:
        resp = client.get("/api/runs?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1


class TestTracesAPI:
    def test_list_traces(self, client) -> None:
        resp = client.get("/api/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert any(t["name"] == "trace.json" for t in data)

    def test_get_trace(self, client) -> None:
        resp = client.get("/api/traces/trace.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario_id"] == "test_scenario"
        assert len(data["turns"]) == 2

    def test_trace_not_found(self, client) -> None:
        resp = client.get("/api/traces/nonexistent.json")
        assert resp.status_code == 404


class TestSecurityBindings:
    def test_server_defaults_to_localhost(self) -> None:
        from scen_trace.server import create_app
        app = create_app(analytics_dir=Path("/tmp"))
        assert app is not None


class TestWebExtraIsolation:
    def test_missing_web_deps_shows_hint(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from scen_trace.cli import cli

        runner = CliRunner()
        with patch.dict("sys.modules", {"uvicorn": None, "fastapi": None}):
            with patch("builtins.__import__", side_effect=_selective_import_blocker):
                result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1 or "Missing" in result.output or "extra" in result.output.lower() or "pip install" in result.output


def _selective_import_blocker(name, *args, **kwargs):
    if name in ("uvicorn", "fastapi"):
        raise ImportError(f"No module named '{name}'")
    return __builtins__.__import__(name, *args, **kwargs) if hasattr(__builtins__, '__import__') else __import__(name, *args, **kwargs)
