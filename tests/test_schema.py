import pytest
from pydantic import ValidationError

from scen_trace.schema import Scenario

VALID_DATA = {
    "scenario_id": "test_scenario",
    "description": "A test",
    "variables": {"user_name": "Alice"},
    "agents": [{"name": "bot", "role": "helper", "system_prompt": "Help"}],
    "model_config": {"provider": "mock", "model_name": "mock-v1"},
    "turns": [{"agent_name": "bot", "prompt": "Hello {{user_name}}", "expected_checks": ["c1"]}],
    "checks": [{"id": "c1", "type": "contains", "params": {"text": "hello"}}],
}


class TestSchema:
    def test_valid_scenario_parses(self):
        s = Scenario(**VALID_DATA)
        assert s.scenario_id == "test_scenario"
        assert len(s.agents) == 1
        assert len(s.turns) == 1

    def test_missing_scenario_id_fails(self):
        data = {k: v for k, v in VALID_DATA.items() if k != "scenario_id"}
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_invalid_temperature_type_fails(self):
        data = {**VALID_DATA, "model_config": {"provider": "mock", "temperature": "hot"}}
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_unknown_check_type_fails(self):
        data = {**VALID_DATA, "checks": [{"id": "c1", "type": "unknown_type", "params": {}}]}
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_undefined_variable_fails(self):
        data = {
            **VALID_DATA,
            "variables": {},
            "turns": [{"agent_name": "bot", "prompt": "Hello {{missing_var}}", "expected_checks": []}],
            "checks": [],
        }
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_turn_references_unknown_agent_fails(self):
        data = {
            **VALID_DATA,
            "turns": [{"agent_name": "nonexistent", "prompt": "Hi", "expected_checks": []}],
            "checks": [],
        }
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_turn_references_unknown_check_fails(self):
        data = {
            **VALID_DATA,
            "turns": [{"agent_name": "bot", "prompt": "Hi", "expected_checks": ["nonexistent"]}],
            "checks": [],
        }
        with pytest.raises(ValidationError):
            Scenario(**data)

    def test_validate_cli_valid_file(self, tmp_path):
        import yaml
        from click.testing import CliRunner
        from scen_trace.cli import cli

        f = tmp_path / "valid.yaml"
        f.write_text(yaml.dump(VALID_DATA))
        result = CliRunner().invoke(cli, ["validate", str(f)])
        assert result.exit_code == 0

    def test_validate_cli_invalid_file(self, tmp_path):
        from click.testing import CliRunner
        from scen_trace.cli import cli

        f = tmp_path / "invalid.yaml"
        f.write_text("agents: []\n")
        result = CliRunner().invoke(cli, ["validate", str(f)])
        assert result.exit_code == 1
