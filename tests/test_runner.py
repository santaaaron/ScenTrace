import json
from pathlib import Path

from click.testing import CliRunner

from scen_trace.cli import cli
from scen_trace.providers.mock import MockProvider
from scen_trace.runner import RunResult, run_scenario, write_trace
from scen_trace.schema import Scenario

SCENARIO_DATA = {
    "scenario_id": "test_run",
    "variables": {"name": "Bob"},
    "agents": [{"name": "bot", "role": "helper", "system_prompt": "Help"}],
    "model_config": {"provider": "mock", "model_name": "mock-v1"},
    "turns": [
        {"agent_name": "bot", "prompt": "Hello {{name}}", "expected_checks": ["c1"]},
        {"agent_name": "bot", "prompt": "Goodbye", "expected_checks": []},
    ],
    "checks": [{"id": "c1", "type": "contains", "params": {"text": "mock response"}}],
}


def _make_scenario(**overrides) -> Scenario:
    data = {**SCENARIO_DATA, **overrides}
    return Scenario(**data)


class TestRunner:
    def test_happy_path(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert result.status == "passed"
        assert len(result.turns) == 2

    def test_variable_injection(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert "Bob" in result.turns[0].prompt

    def test_max_turns_exceeded(self):
        result = run_scenario(_make_scenario(), MockProvider(), max_turns=1)
        assert result.status == "max_turns_exceeded"
        assert len(result.turns) == 1

    def test_error_continues_by_default(self):
        result = run_scenario(_make_scenario(), MockProvider(fail_on_turn=1))
        assert len(result.turns) == 2
        assert result.turns[0].status == "error"

    def test_error_stops_when_configured(self):
        result = run_scenario(_make_scenario(), MockProvider(fail_on_turn=1), stop_on_error=True)
        assert len(result.turns) == 1
        assert result.status == "error"

    def test_duration_captured(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert result.total_duration_ms > 0
        assert all(t.duration_ms >= 0 for t in result.turns)

    def test_cost_calculated(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert result.estimated_cost > 0
        assert result.total_input_tokens > 0
        assert result.total_output_tokens > 0

    def test_checks_evaluated(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert result.checks_passed >= 1
        assert result.turns[0].check_results

    def test_check_failure_sets_status(self):
        s = _make_scenario(
            checks=[{"id": "c1", "type": "contains", "params": {"text": "will_never_match"}}]
        )
        result = run_scenario(s, MockProvider())
        assert result.status == "failed"
        assert result.checks_failed >= 1

    def test_stop_on_fail(self):
        s = _make_scenario(
            checks=[{"id": "c1", "type": "contains", "params": {"text": "will_never_match"}}]
        )
        result = run_scenario(s, MockProvider(), stop_on_fail=True)
        assert result.status == "failed"
        assert len(result.turns) == 1

    def test_callback_invoked(self):
        traces = []
        run_scenario(_make_scenario(), MockProvider(), on_turn_complete=lambda t: traces.append(t))
        assert len(traces) == 2

    def test_to_dict_serializable(self):
        result = run_scenario(_make_scenario(), MockProvider())
        d = result.to_dict()
        json.dumps(d)  # must not raise

    def test_metadata_captured(self):
        result = run_scenario(_make_scenario(), MockProvider())
        assert result.metadata["provider"] == "mock"


class TestWriteTrace:
    def test_json_output(self, tmp_path):
        result = run_scenario(_make_scenario(), MockProvider())
        out = tmp_path / "trace.json"
        write_trace(result, out)
        data = json.loads(out.read_text())
        assert data["scenario_id"] == "test_run"
        assert len(data["turns"]) == 2

    def test_jsonl_output(self, tmp_path):
        result = run_scenario(_make_scenario(), MockProvider())
        out = tmp_path / "trace.jsonl"
        write_trace(result, out)
        lines = [l for l in out.read_text().strip().splitlines() if l.strip()]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # must parse


class TestRunCLI:
    def test_valid_scenario_run(self):
        result = CliRunner().invoke(cli, [
            "run", "examples/basic_scenario.yaml", "--provider", "mock"
        ])
        assert result.exit_code == 0

    def test_max_turns_flag(self):
        result = CliRunner().invoke(cli, [
            "run", "examples/basic_scenario.yaml", "--provider", "mock", "--max-turns", "1"
        ])
        assert result.exit_code == 1  # max_turns_exceeded

    def test_invalid_scenario(self):
        result = CliRunner().invoke(cli, [
            "run", "examples/invalid_scenario.yaml", "--provider", "mock"
        ])
        assert result.exit_code == 1

    def test_json_output(self, tmp_path):
        out = tmp_path / "trace.json"
        result = CliRunner().invoke(cli, [
            "run", "examples/basic_scenario.yaml", "--provider", "mock", "-o", str(out)
        ])
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "scenario_id" in data

    def test_jsonl_output(self, tmp_path):
        out = tmp_path / "trace.jsonl"
        result = CliRunner().invoke(cli, [
            "run", "examples/basic_scenario.yaml", "--provider", "mock", "-o", str(out)
        ])
        assert result.exit_code == 0
        lines = out.read_text().strip().splitlines()
        assert len(lines) >= 1
