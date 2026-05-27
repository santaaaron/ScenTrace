from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points

logger = logging.getLogger(__name__)

PROVIDER_GROUP = "scenetrace.providers"
CHECK_GROUP = "scenetrace.checks"


@dataclass
class DiscoveredPlugin:
    name: str
    group: str
    module: str
    distribution: str
    version: str
    loaded: bool = False
    error: str | None = None
    obj: object | None = field(default=None, repr=False)


def discover_plugins(group: str) -> list[DiscoveredPlugin]:
    """Discover entry points for a given group without loading them."""
    try:
        group_eps = entry_points(group=group)
    except TypeError:
        eps = entry_points()
        group_eps = eps.get(group, [])

    plugins: list[DiscoveredPlugin] = []
    for ep in group_eps:
        dist = ep.dist
        plugins.append(DiscoveredPlugin(
            name=ep.name,
            group=group,
            module=ep.value,
            distribution=dist.name if dist else "unknown",
            version=dist.version if dist else "unknown",
        ))
    return plugins


def load_plugin(plugin: DiscoveredPlugin) -> DiscoveredPlugin:
    """Attempt to load a discovered plugin's entry point."""
    try:
        group_eps = entry_points(group=plugin.group)
    except TypeError:
        eps = entry_points()
        group_eps = eps.get(plugin.group, [])

    for ep in group_eps:
        if ep.name == plugin.name:
            try:
                obj = ep.load()
                plugin.obj = obj
                plugin.loaded = True
            except Exception as e:
                plugin.error = str(e)
                plugin.loaded = False
                logger.warning("Failed to load plugin '%s' from %s: %s", plugin.name, plugin.module, e)
            return plugin

    plugin.error = "Entry point not found"
    plugin.loaded = False
    return plugin


def discover_providers() -> dict[str, DiscoveredPlugin]:
    """Discover all provider plugins."""
    return {p.name: p for p in discover_plugins(PROVIDER_GROUP)}


def discover_checks() -> dict[str, DiscoveredPlugin]:
    """Discover all check plugins."""
    return {p.name: p for p in discover_plugins(CHECK_GROUP)}
