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

    def test_plugin_check_type_passes_validation(self, monkeypatch):
        from unittest.mock import MagicMock
        from scen_trace.plugins import DiscoveredPlugin

        fake_plugin = DiscoveredPlugin(
            name="custom_check", group="scenetrace.checks",
            module="fake.module", distribution="fake-pkg", version="1.0",
        )
        monkeypatch.setattr("scen_trace.schema.discover_checks", lambda: {"custom_check": fake_plugin}, raising=False)
        import scen_trace.schema
        monkeypatch.setattr(scen_trace.schema, "discover_checks", lambda: {"custom_check": fake_plugin})
        # Need to patch the import within the validator
        import importlib
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        def patched_import(name, *args, **kwargs):
            return original_import(name, *args, **kwargs)
        # Just test that the check model accepts plugin types when discover_checks is available
        from scen_trace.schema import Check
        # Monkeypatch the discover_checks import inside the Check validator
        import scen_trace.plugins as plugins_mod
        monkeypatch.setattr(plugins_mod, "discover_checks", lambda: {"custom_check": fake_plugin})
        c = Check(id="c1", type="custom_check", params={})
        assert c.type == "custom_check"

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
