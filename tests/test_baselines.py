import json
from pathlib import Path

from click.testing import CliRunner

from scen_trace.baselines import BaselineRegistry, _compute_trace_hash
from scen_trace.cli import cli
from scen_trace.report import TraceData


def _make_trace_json(tmp_path: Path, **overrides) -> Path:
    data = {
        "scenario_id": "test_scenario",
        "status": "passed",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "total_duration_ms": 150.0,
        "total_input_tokens": 40,
        "total_output_tokens": 20,
        "estimated_cost": 0.00006,
        "checks_passed": 1,
        "checks_failed": 0,
        "metadata": {"provider": "mock", "model": "mock-v1"},
        "turns": [
            {
                "turn_index": 0,
                "agent_name": "greeter",
                "prompt": "Hello",
                "response": "Hi there!",
                "timestamp": "2026-01-01T00:00:00Z",
                "model": "mock-v1",
                "provider": "mock",
                "input_tokens": 40,
                "output_tokens": 20,
                "duration_ms": 150.0,
                "status": "success",
                "check_results": [{"check_id": "c1", "check_type": "contains", "passed": True, "message": "OK"}],
            }
        ],
    }
    data.update(overrides)
    tmp_path.mkdir(parents=True, exist_ok=True)
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(data, indent=2))
    return trace_file


class TestBaselineRegistry:
    def test_init_creates_db(self, tmp_path):
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        assert (tmp_path / "bl" / "baselines.db").exists()
        assert (tmp_path / "bl" / "baselines").is_dir()
        registry.close()

    def test_save_and_get(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()

        entry = registry.save(trace_file, "v1.0")
        assert entry.tag == "v1.0"
        assert entry.scenario_id == "test_scenario"
        assert entry.status == "passed"
        assert entry.estimated_cost == 0.00006

        retrieved = registry.get_baseline("v1.0")
        assert retrieved is not None
        assert retrieved.tag == "v1.0"
        registry.close()

    def test_save_tag_collision_without_force(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        try:
            registry.save(trace_file, "v1.0")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already exists" in str(e)
        registry.close()

    def test_save_tag_collision_with_force(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        entry = registry.save(trace_file, "v1.0", force=True)
        assert entry.tag == "v1.0"
        baselines = registry.list_baselines()
        assert len(baselines) == 1
        registry.close()

    def test_list_baselines(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")
        registry.save(trace_file, "v2.0")

        entries = registry.list_baselines()
        assert len(entries) == 2
        tags = {e.tag for e in entries}
        assert tags == {"v1.0", "v2.0"}
        registry.close()

    def test_remove_baseline(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        assert registry.remove("v1.0")
        assert registry.get_baseline("v1.0") is None
        assert not registry.remove("nonexistent")
        registry.close()

    def test_get_nonexistent(self, tmp_path):
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        assert registry.get_baseline("nope") is None
        registry.close()


class TestDriftDetection:
    def test_identical_traces_stable(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        result = registry.compare(trace_file, "v1.0")
        assert result.overall == "stable"
        assert all(d.severity == "ok" for d in result.drifts)
        assert len(result.check_flips) == 0
        registry.close()

    def test_cost_spike_critical(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        expensive_trace = _make_trace_json(tmp_path / "sub", estimated_cost=0.001)
        result = registry.compare(expensive_trace, "v1.0")
        cost_drift = next(d for d in result.drifts if d.field == "estimated_cost")
        assert cost_drift.severity == "critical"
        assert result.overall == "regression"
        registry.close()

    def test_latency_increase_warning(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        slow_trace = _make_trace_json(tmp_path / "sub", total_duration_ms=500.0)
        result = registry.compare(slow_trace, "v1.0")
        latency_drift = next(d for d in result.drifts if d.field == "total_duration_ms")
        assert latency_drift.severity == "warning"
        registry.close()

    def test_status_change_critical(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        failed_trace = _make_trace_json(tmp_path / "sub", status="failed")
        result = registry.compare(failed_trace, "v1.0")
        status_drift = next(d for d in result.drifts if d.field == "status")
        assert status_drift.severity == "critical"
        assert result.overall == "regression"
        registry.close()

    def test_check_flip_regression(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        flipped_turns = [{
            "turn_index": 0,
            "agent_name": "greeter",
            "prompt": "Hello",
            "response": "Hi there!",
            "timestamp": "2026-01-01T00:00:00Z",
            "input_tokens": 40,
            "output_tokens": 20,
            "duration_ms": 150.0,
            "status": "success",
            "check_results": [{"check_id": "c1", "check_type": "contains", "passed": False, "message": "Missing"}],
        }]
        flipped_trace = _make_trace_json(
            tmp_path / "sub",
            turns=flipped_turns,
            checks_passed=0,
            checks_failed=1,
            status="failed",
        )
        result = registry.compare(flipped_trace, "v1.0")
        assert len(result.check_flips) == 1
        assert result.check_flips[0]["direction"] == "regression"
        assert result.overall == "regression"
        registry.close()

    def test_compare_nonexistent_tag(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        try:
            registry.compare(trace_file, "nope")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No baseline found" in str(e)
        registry.close()

    def test_custom_thresholds(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        registry = BaselineRegistry(baselines_dir=tmp_path / "bl")
        registry.init()
        registry.save(trace_file, "v1.0")

        # 5% cost increase with 1% threshold should be critical
        slightly_expensive = _make_trace_json(tmp_path / "sub", estimated_cost=0.000063)
        result = registry.compare(slightly_expensive, "v1.0", cost_threshold_pct=1.0)
        cost_drift = next(d for d in result.drifts if d.field == "estimated_cost")
        assert cost_drift.severity == "critical"
        registry.close()


class TestTraceHash:
    def test_same_content_same_hash(self, tmp_path):
        trace1 = TraceData(
            scenario_id="s1", status="passed", started_at="", finished_at="",
            total_duration_ms=0, total_input_tokens=0, total_output_tokens=0,
            estimated_cost=0, checks_passed=0, checks_failed=0, metadata={},
            turns=[{"prompt": "hello", "response": "world"}],
        )
        trace2 = TraceData(
            scenario_id="s1", status="passed", started_at="", finished_at="",
            total_duration_ms=0, total_input_tokens=0, total_output_tokens=0,
            estimated_cost=0, checks_passed=0, checks_failed=0, metadata={},
            turns=[{"prompt": "hello", "response": "world"}],
        )
        assert _compute_trace_hash(trace1) == _compute_trace_hash(trace2)

    def test_different_content_different_hash(self, tmp_path):
        trace1 = TraceData(
            scenario_id="s1", status="passed", started_at="", finished_at="",
            total_duration_ms=0, total_input_tokens=0, total_output_tokens=0,
            estimated_cost=0, checks_passed=0, checks_failed=0, metadata={},
            turns=[{"prompt": "hello", "response": "world"}],
        )
        trace2 = TraceData(
            scenario_id="s1", status="passed", started_at="", finished_at="",
            total_duration_ms=0, total_input_tokens=0, total_output_tokens=0,
            estimated_cost=0, checks_passed=0, checks_failed=0, metadata={},
            turns=[{"prompt": "hello", "response": "different"}],
        )
        assert _compute_trace_hash(trace1) != _compute_trace_hash(trace2)


class TestBaselineCLI:
    def test_baseline_init(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["baseline", "init"])
            assert result.exit_code == 0
            assert "initialized" in result.output.lower()
            assert Path(".scenetrace/baselines.db").exists()

    def test_baseline_save_and_list(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["baseline", "init", "--dir", str(tmp_path / "bl")])
            result = runner.invoke(cli, ["baseline", "save", str(trace_file), "--tag", "v1.0", "--dir", str(tmp_path / "bl")])
            assert result.exit_code == 0
            assert "v1.0" in result.output

            result = runner.invoke(cli, ["baseline", "list", "--dir", str(tmp_path / "bl")])
            assert result.exit_code == 0
            assert "v1.0" in result.output

    def test_baseline_compare_stable(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        runner = CliRunner()
        bl_dir = str(tmp_path / "bl")
        runner.invoke(cli, ["baseline", "init", "--dir", bl_dir])
        runner.invoke(cli, ["baseline", "save", str(trace_file), "--tag", "v1.0", "--dir", bl_dir])

        result = runner.invoke(cli, ["baseline", "compare", str(trace_file), "--tag", "v1.0", "--dir", bl_dir])
        assert result.exit_code == 0
        assert "STABLE" in result.output

    def test_baseline_compare_regression_exits_1(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        runner = CliRunner()
        bl_dir = str(tmp_path / "bl")
        runner.invoke(cli, ["baseline", "init", "--dir", bl_dir])
        runner.invoke(cli, ["baseline", "save", str(trace_file), "--tag", "v1.0", "--dir", bl_dir])

        expensive_trace = _make_trace_json(tmp_path / "sub", estimated_cost=0.01, status="failed")
        result = runner.invoke(cli, ["baseline", "compare", str(expensive_trace), "--tag", "v1.0", "--dir", bl_dir])
        assert result.exit_code == 1

    def test_baseline_rm(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        runner = CliRunner()
        bl_dir = str(tmp_path / "bl")
        runner.invoke(cli, ["baseline", "init", "--dir", bl_dir])
        runner.invoke(cli, ["baseline", "save", str(trace_file), "--tag", "v1.0", "--dir", bl_dir])

        result = runner.invoke(cli, ["baseline", "rm", "v1.0", "--dir", bl_dir])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

    def test_baseline_compare_missing_tag(self, tmp_path):
        trace_file = _make_trace_json(tmp_path)
        runner = CliRunner()
        bl_dir = str(tmp_path / "bl")
        runner.invoke(cli, ["baseline", "init", "--dir", bl_dir])

        result = runner.invoke(cli, ["baseline", "compare", str(trace_file), "--tag", "nope", "--dir", bl_dir])
        assert result.exit_code == 1
        assert "no baseline found" in result.output.lower()
