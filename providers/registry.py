"""Maps a pool's `provider` string to a Provider implementation.

The reconciler looks up the backend here, so adding a new cloud is one line and
zero changes to the control loop.
"""
from __future__ import annotations

from .base import Provider
from .aws import AWSProvider
from .gcp import GCPProvider
from .azure import AzureProvider
from .baremetal import BareMetalProvider

_FACTORIES = {
    "aws": AWSProvider,
    "gcp": GCPProvider,
    "azure": AzureProvider,
    "baremetal": BareMetalProvider,
}


class ProviderRegistry:
    """Holds one live Provider instance per backend (so the simulated fleet
    persists across reconcile ticks)."""

    def __init__(self, failure_rate: float = 0.0):
        self._instances: dict[str, Provider] = {}
        self._failure_rate = failure_rate

    def get(self, name: str) -> Provider:
        if name not in self._instances:
            if name not in _FACTORIES:
                raise KeyError(f"unknown provider: {name}")
            self._instances[name] = _FACTORIES[name](failure_rate=self._failure_rate)
        return self._instances[name]
