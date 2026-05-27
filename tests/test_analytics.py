from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from scen_trace.analytics import AnalyticsDB, EfficiencyScore, RunRecord, TrendData
from scen_trace.cli import cli
from scen_trace.report import TraceData


def _make_trace_data(
    scenario_id: str = "test_scenario",
    status: str = "passed",
    cost: float = 0.000061,
    duration_ms: float = 5.0,
    input_tokens: int = 40,
    output_tokens: int = 21,
    checks_passed: int = 1,
    checks_failed: int = 0,
) -> TraceData:
    return TraceData(
        scenario_id=scenario_id,
        status=status,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        total_duration_ms=duration_ms,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        estimated_cost=cost,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        metadata={"provider": "mock", "model": "mock-v1"},
        turns=[
            {
                "turn_index": 0,
                "agent_name": "greeter",
                "prompt": "Hello",
                "response": "Hi there!",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "model": "mock-v1",
                "provider": "mock",
                "input_tokens": 20,
                "output_tokens": 10,
                "duration_ms": 2.0,
                "status": "success",
                "check_results": [],
            },
            {
                "turn_index": 1,
                "agent_name": "validator",
                "prompt": "Check something",
                "response": "Looks good",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "model": "mock-v1",
                "provider": "mock",
                "input_tokens": 20,
                "output_tokens": 11,
                "duration_ms": 3.0,
                "status": "success",
                "check_results": [],
            },
        ],
    )


def _write_trace_file(tmp: Path, trace_data: TraceData) -> Path:
    trace_path = tmp / "trace.json"
    trace_dict = {
        "scenario_id": trace_data.scenario_id,
        "status": trace_data.status,
        "started_at": trace_data.started_at,
        "finished_at": trace_data.finished_at,
        "total_duration_ms": trace_data.total_duration_ms,
        "total_input_tokens": trace_data.total_input_tokens,
        "total_output_tokens": trace_data.total_output_tokens,
        "estimated_cost": trace_data.estimated_cost,
        "checks_passed": trace_data.checks_passed,
        "checks_failed": trace_data.checks_failed,
        "metadata": trace_data.metadata,
        "turns": trace_data.turns,
    }
    trace_path.write_text(json.dumps(trace_dict, indent=2))
    return trace_path


class TestAnalyticsDB:
    def test_init_creates_db(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        assert (tmp_path / "analytics.db").exists()
        db.close()

    def test_init_idempotent(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        db.init()
        assert (tmp_path / "analytics.db").exists()
        db.close()

    def test_ingest_run(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        trace_data = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, trace_data)
        run_id = db.ingest_run(trace_path, trace_data=trace_data)
        assert run_id == 1
        runs = db.get_runs()
        assert len(runs) == 1
        assert runs[0].scenario_id == "test_scenario"
        assert runs[0].status == "passed"
        db.close()

    def test_ingest_from_file(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        trace_data = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, trace_data)
        run_id = db.ingest_run(trace_path)
        assert run_id == 1
        db.close()

    def test_get_runs_by_scenario(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        td1 = _make_trace_data(scenario_id="scenario_a")
        td2 = _make_trace_data(scenario_id="scenario_b")
        tp1 = _write_trace_file(tmp_path, td1)
        tp2 = tmp_path / "trace2.json"
        tp2.write_text(json.dumps({
            "scenario_id": td2.scenario_id, "status": td2.status,
            "started_at": "", "finished_at": "",
            "total_duration_ms": td2.total_duration_ms,
            "total_input_tokens": td2.total_input_tokens,
            "total_output_tokens": td2.total_output_tokens,
            "estimated_cost": td2.estimated_cost,
            "checks_passed": td2.checks_passed, "checks_failed": td2.checks_failed,
            "metadata": {}, "turns": td2.turns,
        }))
        db.ingest_run(tp1, trace_data=td1)
        db.ingest_run(tp2, trace_data=td2)
        runs_a = db.get_runs(scenario_id="scenario_a")
        assert len(runs_a) == 1
        assert runs_a[0].scenario_id == "scenario_a"
        db.close()

    def test_agent_metrics(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        trace_data = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, trace_data)
        run_id = db.ingest_run(trace_path, trace_data=trace_data)
        metrics = db.get_agent_metrics(run_id)
        assert len(metrics) == 2
        names = {m.agent_name for m in metrics}
        assert "greeter" in names
        assert "validator" in names
        db.close()

    def test_multiple_runs_tracking(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        for i in range(5):
            td = _make_trace_data(cost=0.0001 * (i + 1))
            tp = _write_trace_file(tmp_path, td)
            db.ingest_run(tp, trace_data=td)
        runs = db.get_runs()
        assert len(runs) == 5
        db.close()


class TestTrends:
    def test_empty_trends(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        trends = db.get_trends("nonexistent")
        assert trends.total_runs == 0
        assert trends.avg_cost == 0.0
        db.close()

    def test_trends_calculation(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        for i in range(3):
            td = _make_trace_data(cost=0.0001 * (i + 1), duration_ms=100 * (i + 1))
            tp = _write_trace_file(tmp_path, td)
            db.ingest_run(tp, trace_data=td)
        trends = db.get_trends("test_scenario")
        assert trends.total_runs == 3
        assert trends.avg_cost > 0
        assert trends.avg_latency_ms > 0
        assert trends.pass_rate_pct == 100.0
        db.close()

    def test_pass_rate_with_failures(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        td_pass = _make_trace_data(status="passed")
        td_fail = _make_trace_data(status="failed")
        tp = _write_trace_file(tmp_path, td_pass)
        db.ingest_run(tp, trace_data=td_pass)
        db.ingest_run(tp, trace_data=td_fail)
        trends = db.get_trends("test_scenario")
        assert trends.pass_rate_pct == 50.0
        db.close()


class TestEfficiency:
    def test_efficiency_no_runs(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        eff = db.compute_efficiency("nonexistent")
        assert eff.total == 0
        db.close()

    def test_efficiency_perfect_score(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        for _ in range(5):
            td = _make_trace_data(status="passed", cost=0.0001, duration_ms=50)
            tp = _write_trace_file(tmp_path, td)
            db.ingest_run(tp, trace_data=td)
        eff = db.compute_efficiency("test_scenario")
        assert eff.total > 0
        assert eff.check_score == 100
        assert eff.cost_score > 80
        assert eff.latency_score > 80
        db.close()

    def test_efficiency_with_failures(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        for i in range(4):
            status = "passed" if i < 2 else "failed"
            td = _make_trace_data(status=status)
            tp = _write_trace_file(tmp_path, td)
            db.ingest_run(tp, trace_data=td)
        eff = db.compute_efficiency("test_scenario")
        assert eff.check_score == 50
        db.close()

    def test_efficiency_details(self, tmp_path: Path) -> None:
        db = AnalyticsDB(analytics_dir=tmp_path)
        db.init()
        td = _make_trace_data()
        tp = _write_trace_file(tmp_path, td)
        db.ingest_run(tp, trace_data=td)
        eff = db.compute_efficiency("test_scenario")
        assert "check_pass_rate" in eff.details
        assert "avg_cost" in eff.details
        assert "total_runs" in eff.details
        db.close()


class TestAnalyticsCLI:
    def test_analytics_init(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["analytics", "init"])
            assert result.exit_code == 0
            assert "initialized" in result.output.lower()

    def test_analytics_track(self, tmp_path: Path) -> None:
        runner = CliRunner()
        td = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, td)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["analytics", "init"])
            result = runner.invoke(cli, ["analytics", "track", str(trace_path)])
            assert result.exit_code == 0
            assert "ingested" in result.output.lower()

    def test_analytics_report_empty(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["analytics", "init"])
            result = runner.invoke(cli, ["analytics", "report", "nonexistent"])
            assert result.exit_code == 0
            assert "no runs found" in result.output.lower()

    def test_analytics_report_with_data(self, tmp_path: Path) -> None:
        runner = CliRunner()
        td = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, td)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["analytics", "init"])
            runner.invoke(cli, ["analytics", "track", str(trace_path)])
            result = runner.invoke(cli, ["analytics", "report", "test_scenario"])
            assert result.exit_code == 0
            assert "efficiency" in result.output.lower()
            assert "test_scenario" in result.output

    def test_run_with_track_flag(self, tmp_path: Path) -> None:
        runner = CliRunner()
        scenario_path = tmp_path / "scenario.yaml"
        scenario_path.write_text(
            "scenario_id: track_test\n"
            "agents:\n"
            "  - name: bot\n"
            "    role: assistant\n"
            "    system_prompt: Test\n"
            "model_config:\n"
            "  provider: mock\n"
            "  model_name: mock-v1\n"
            "turns:\n"
            "  - agent_name: bot\n"
            "    prompt: hello\n"
            "    expected_checks: []\n"
            "checks: []\n"
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, [
                "run", str(scenario_path),
                "--provider", "mock",
                "--track",
                "--analytics-dir", str(tmp_path),
            ])
            assert result.exit_code == 0
            assert "tracked" in result.output.lower()
            assert (tmp_path / "analytics.db").exists()

    def test_analytics_report_shows_agents(self, tmp_path: Path) -> None:
        runner = CliRunner()
        td = _make_trace_data()
        trace_path = _write_trace_file(tmp_path, td)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["analytics", "init"])
            runner.invoke(cli, ["analytics", "track", str(trace_path)])
            result = runner.invoke(cli, ["analytics", "report", "test_scenario"])
            assert result.exit_code == 0
            assert "greeter" in result.output
            assert "validator" in result.output
