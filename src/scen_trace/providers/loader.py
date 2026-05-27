from __future__ import annotations

import logging

from scen_trace.providers import BaseProvider

logger = logging.getLogger(__name__)


class ProviderNotInstalledError(Exception):
    pass


_INSTALL_HINTS = {
    "openai": "pip install scen-trace[openai]",
    "anthropic": "pip install scen-trace[anthropic]",
}

_BUILTIN_PROVIDERS = {"mock", "openai"}


def get_provider(name: str) -> BaseProvider:
    if name == "mock":
        from scen_trace.providers.mock import MockProvider
        return MockProvider()

    if name == "openai":
        try:
            import importlib
            importlib.import_module("openai")
        except ImportError:
            hint = _INSTALL_HINTS.get("openai", "")
            raise ProviderNotInstalledError(
                f"OpenAI provider requires extra dependencies. Install with: {hint}"
            )
        from scen_trace.providers.openai import OpenAIProvider
        return OpenAIProvider()

    # Check for plugin-provided providers
    try:
        from scen_trace.plugins import discover_providers, load_plugin
        plugins = discover_providers()
        if name in plugins:
            plugin = load_plugin(plugins[name])
            if plugin.loaded and plugin.obj is not None:
                provider_cls = plugin.obj
                return provider_cls()
            raise ProviderNotInstalledError(
                f"Plugin provider '{name}' failed to load: {plugin.error}"
            )
    except ImportError:
        pass

    available = list(_BUILTIN_PROVIDERS)
    try:
        from scen_trace.plugins import discover_providers
        available.extend(discover_providers().keys())
    except ImportError:
        pass

    raise ValueError(f"Unknown provider '{name}'. Available: {', '.join(sorted(set(available)))}")
