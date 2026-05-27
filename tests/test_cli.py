from click.testing import CliRunner

from scen_trace import __version__
from scen_trace.cli import cli


class TestCLI:
    def test_version_flag(self):
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help_flag(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ScenTrace" in result.output

    def test_init_command(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            assert "ScenTrace" in result.output

    def test_no_args_shows_help(self):
        result = CliRunner().invoke(cli, [])
        assert result.exit_code == 0
        assert "ScenTrace" in result.output

    def test_sync_placeholder(self):
        result = CliRunner().invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "V2" in result.output
        assert "syncing" in result.output.lower()
