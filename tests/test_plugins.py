from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from scen_trace.cli import cli
from scen_trace.plugins import (
    CHECK_GROUP,
    PROVIDER_GROUP,
    DiscoveredPlugin,
    discover_checks,
    discover_plugins,
    discover_providers,
    load_plugin,
)
from scen_trace.providers import BaseProvider, ProviderResponse


def _mock_entry_points(mapping: dict[str, list]):
    """Create a mock entry_points function that handles group= kwarg."""
    def _ep(*, group=None):
        if group is not None:
            return mapping.get(group, [])
        return mapping
    return _ep


class TestPluginDiscovery:
    def test_discover_empty_when_no_plugins(self):
        with patch("scen_trace.plugins.entry_points", _mock_entry_points({})):
            result = discover_plugins(PROVIDER_GROUP)
        assert result == []

    def test_discover_providers_returns_dict(self):
        with patch("scen_trace.plugins.entry_points", _mock_entry_points({})):
            result = discover_providers()
        assert result == {}

    def test_discover_checks_returns_dict(self):
        with patch("scen_trace.plugins.entry_points", _mock_entry_points({})):
            result = discover_checks()
        assert result == {}

    def test_discover_finds_registered_entry_points(self):
        mock_ep = MagicMock()
        mock_ep.name = "custom_provider"
        mock_ep.value = "my_plugin.providers:CustomProvider"
        mock_ep.dist = MagicMock()
        mock_ep.dist.name = "scenetrace-custom"
        mock_ep.dist.version = "0.1.0"

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [mock_ep]})):
            result = discover_plugins(PROVIDER_GROUP)

        assert len(result) == 1
        assert result[0].name == "custom_provider"
        assert result[0].distribution == "scenetrace-custom"
        assert result[0].version == "0.1.0"
        assert result[0].module == "my_plugin.providers:CustomProvider"

    def test_discover_multiple_plugins(self):
        ep1 = MagicMock()
        ep1.name = "azure"
        ep1.value = "scenetrace_azure:AzureProvider"
        ep1.dist = MagicMock()
        ep1.dist.name = "scenetrace-azure"
        ep1.dist.version = "1.0.0"

        ep2 = MagicMock()
        ep2.name = "bedrock"
        ep2.value = "scenetrace_bedrock:BedrockProvider"
        ep2.dist = MagicMock()
        ep2.dist.name = "scenetrace-bedrock"
        ep2.dist.version = "0.5.0"

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [ep1, ep2]})):
            result = discover_providers()

        assert "azure" in result
        assert "bedrock" in result


class TestPluginLoading:
    def test_load_plugin_success(self):
        class FakeProvider(BaseProvider):
            def generate(self, system_prompt: str, prompt: str, **kwargs) -> ProviderResponse:
                return ProviderResponse(content="fake")

        mock_ep = MagicMock()
        mock_ep.name = "fake"
        mock_ep.value = "fake_mod:FakeProvider"
        mock_ep.dist = MagicMock()
        mock_ep.dist.name = "scenetrace-fake"
        mock_ep.dist.version = "1.0.0"
        mock_ep.load.return_value = FakeProvider

        plugin = DiscoveredPlugin(
            name="fake", group=PROVIDER_GROUP,
            module="fake_mod:FakeProvider",
            distribution="scenetrace-fake", version="1.0.0",
        )

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [mock_ep]})):
            loaded = load_plugin(plugin)

        assert loaded.loaded is True
        assert loaded.error is None
        assert loaded.obj is FakeProvider

    def test_load_plugin_import_error(self):
        mock_ep = MagicMock()
        mock_ep.name = "broken"
        mock_ep.value = "broken_mod:BrokenProvider"
        mock_ep.dist = MagicMock()
        mock_ep.dist.name = "scenetrace-broken"
        mock_ep.dist.version = "0.1.0"
        mock_ep.load.side_effect = ImportError("No module named 'broken_mod'")

        plugin = DiscoveredPlugin(
            name="broken", group=PROVIDER_GROUP,
            module="broken_mod:BrokenProvider",
            distribution="scenetrace-broken", version="0.1.0",
        )

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [mock_ep]})):
            loaded = load_plugin(plugin)

        assert loaded.loaded is False
        assert "No module named" in loaded.error

    def test_load_plugin_not_found(self):
        plugin = DiscoveredPlugin(
            name="nonexistent", group=PROVIDER_GROUP,
            module="nope:Nope",
            distribution="unknown", version="0.0.0",
        )

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({})):
            loaded = load_plugin(plugin)

        assert loaded.loaded is False
        assert loaded.error == "Entry point not found"


class TestProviderLoaderIntegration:
    def test_builtin_mock_still_works(self):
        from scen_trace.providers.loader import get_provider
        provider = get_provider("mock")
        assert provider is not None

    def test_unknown_provider_checks_plugins(self):
        from scen_trace.providers.loader import get_provider
        with patch("scen_trace.plugins.discover_providers", return_value={}):
            try:
                get_provider("nonexistent_plugin")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "Unknown provider" in str(e)

    def test_plugin_provider_loads(self):
        class PluginProvider(BaseProvider):
            def generate(self, system_prompt: str, prompt: str, **kwargs) -> ProviderResponse:
                return ProviderResponse(content="plugin response")

        plugin = DiscoveredPlugin(
            name="custom", group=PROVIDER_GROUP,
            module="custom_mod:PluginProvider",
            distribution="scenetrace-custom", version="1.0.0",
        )

        with patch("scen_trace.plugins.discover_providers", return_value={"custom": plugin}), \
             patch("scen_trace.plugins.load_plugin") as mock_load:
            mock_load.return_value = DiscoveredPlugin(
                name="custom", group=PROVIDER_GROUP,
                module="custom_mod:PluginProvider",
                distribution="scenetrace-custom", version="1.0.0",
                loaded=True, obj=PluginProvider,
            )
            from scen_trace.providers.loader import get_provider
            provider = get_provider("custom")
            assert isinstance(provider, PluginProvider)


class TestCheckPluginIntegration:
    def test_plugin_check_evaluates(self):
        from scen_trace.checks import evaluate_check

        def my_check(response: str, params: dict) -> bool:
            return "hello" in response.lower()

        plugin = DiscoveredPlugin(
            name="custom_check", group=CHECK_GROUP,
            module="custom_mod:my_check",
            distribution="scenetrace-custom-check", version="1.0.0",
        )

        with patch("scen_trace.plugins.discover_checks", return_value={"custom_check": plugin}), \
             patch("scen_trace.plugins.load_plugin") as mock_load:
            mock_load.return_value = DiscoveredPlugin(
                name="custom_check", group=CHECK_GROUP,
                module="custom_mod:my_check",
                distribution="scenetrace-custom-check", version="1.0.0",
                loaded=True, obj=my_check,
            )
            result = evaluate_check("chk_1", "custom_check", {}, "Hello world")
            assert result.passed is True

    def test_unknown_check_falls_through(self):
        from scen_trace.checks import evaluate_check
        with patch("scen_trace.plugins.discover_checks", return_value={}):
            result = evaluate_check("chk_1", "totally_unknown", {}, "test")
            assert result.passed is False
            assert "Unknown check type" in result.message


class TestPluginListCLI:
    def test_plugin_list_empty(self):
        runner = CliRunner()
        with patch("scen_trace.plugins.entry_points", _mock_entry_points({})):
            result = runner.invoke(cli, ["plugin", "list"])
        assert result.exit_code == 0
        assert "No external plugins" in result.output

    def test_plugin_list_with_plugins(self):
        mock_ep = MagicMock()
        mock_ep.name = "azure"
        mock_ep.value = "scenetrace_azure:AzureProvider"
        mock_ep.dist = MagicMock()
        mock_ep.dist.name = "scenetrace-azure"
        mock_ep.dist.version = "2.0.0"
        mock_ep.load.return_value = type("AzureProvider", (), {})

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [mock_ep]})):
            runner = CliRunner()
            result = runner.invoke(cli, ["plugin", "list"])
        assert result.exit_code == 0
        assert "azure" in result.output
        assert "provider" in result.output

    def test_plugin_list_shows_load_error(self):
        mock_ep = MagicMock()
        mock_ep.name = "broken"
        mock_ep.value = "broken_mod:Broken"
        mock_ep.dist = MagicMock()
        mock_ep.dist.name = "scenetrace-broken"
        mock_ep.dist.version = "0.1.0"
        mock_ep.load.side_effect = ImportError("Module not found")

        with patch("scen_trace.plugins.entry_points", _mock_entry_points({PROVIDER_GROUP: [mock_ep]})):
            runner = CliRunner()
            result = runner.invoke(cli, ["plugin", "list"])
        assert result.exit_code == 0
        assert "broken" in result.output
        assert "Error" in result.output
