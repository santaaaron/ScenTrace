from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scen_trace.cli import cli
from scen_trace.scaffold import scaffold_project


class TestScaffoldProject:
    def test_creates_all_files(self, tmp_path: Path) -> None:
        target = tmp_path / ".scenetrace"
        created, skipped = scaffold_project(target)

        assert len(created) == 3
        assert len(skipped) == 0
        assert (target / "example_scenario.yaml").exists()
        assert (target / ".env.example").exists()
        assert (target / ".gitignore").exists()

    def test_skips_existing_files(self, tmp_path: Path) -> None:
        target = tmp_path / ".scenetrace"
        target.mkdir()
        (target / "example_scenario.yaml").write_text("existing")

        created, skipped = scaffold_project(target)

        assert len(created) == 2
        assert len(skipped) == 1
        assert (target / "example_scenario.yaml").read_text() == "existing"

    def test_all_files_exist_skips_all(self, tmp_path: Path) -> None:
        target = tmp_path / ".scenetrace"
        target.mkdir()
        (target / "example_scenario.yaml").write_text("a")
        (target / ".env.example").write_text("b")
        (target / ".gitignore").write_text("c")

        created, skipped = scaffold_project(target)

        assert len(created) == 0
        assert len(skipped) == 3

    def test_scenario_is_valid_yaml(self, tmp_path: Path) -> None:
        from scen_trace.validator import load_scenario

        target = tmp_path / ".scenetrace"
        scaffold_project(target)

        scenario = load_scenario(target / "example_scenario.yaml")
        assert scenario.scenario_id == "hello_world"
        assert len(scenario.agents) == 1
        assert len(scenario.turns) == 1


class TestInitCLI:
    def test_init_creates_files(self, tmp_path: Path) -> None:
        runner = CliRunner()
        target = str(tmp_path / ".scenetrace")
        result = runner.invoke(cli, ["init", "--dir", target])

        assert result.exit_code == 0
        assert "Project scaffolded" in result.output
        assert Path(target, "example_scenario.yaml").exists()

    def test_init_shows_skipped(self, tmp_path: Path) -> None:
        target = tmp_path / ".scenetrace"
        target.mkdir()
        (target / "example_scenario.yaml").write_text("existing")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0
        assert "exists, skipped" in result.output

    def test_init_all_exist(self, tmp_path: Path) -> None:
        target = tmp_path / ".scenetrace"
        target.mkdir()
        (target / "example_scenario.yaml").write_text("a")
        (target / ".env.example").write_text("b")
        (target / ".gitignore").write_text("c")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0
        assert "Nothing created" in result.output

    def test_init_default_dir(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            assert Path(".scenetrace/example_scenario.yaml").exists()
