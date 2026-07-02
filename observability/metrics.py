"""A minimal, dependency-free Prometheus-style metrics registry.

In production you'd use the official client + Thanos/Cortex for long-term,
global-scale storage. This implementation mirrors the data model (counters,
gauges, labels, exposition format) so the rest of the system is instrumented
exactly as it would be in prod, and `render_prometheus()` emits text that a real
Prometheus server could scrape verbatim.
"""
from __future__ import annotations

import threading


def _labels_key(labels: dict) -> tuple:
    return tuple(sorted(labels.items()))


def _fmt_labels(labels: dict) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


class _Metric:
    def __init__(self, name: str, help_: str, mtype: str):
        self.name = name
        self.help = help_
        self.type = mtype
        self.samples: dict[tuple, float] = {}


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._metrics: dict[str, _Metric] = {}

    def counter(self, name: str, help_: str = "") -> "Counter":
        return Counter(self, name, help_)

    def gauge(self, name: str, help_: str = "") -> "Gauge":
        return Gauge(self, name, help_)

    def _metric(self, name: str, help_: str, mtype: str) -> _Metric:
        with self._lock:
            m = self._metrics.get(name)
            if m is None:
                m = _Metric(name, help_, mtype)
                self._metrics[name] = m
            return m

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for m in self._metrics.values():
                if m.help:
                    lines.append(f"# HELP {m.name} {m.help}")
                lines.append(f"# TYPE {m.name} {m.type}")
                for key, val in sorted(m.samples.items()):
                    labels = dict(key)
                    lines.append(f"{m.name}{_fmt_labels(labels)} {val:g}")
        return "\n".join(lines) + "\n"

    def snapshot(self) -> dict:
        """Flat {(name, labels_tuple): value} snapshot for the dashboard."""
        with self._lock:
            out = {}
            for m in self._metrics.values():
                for key, val in m.samples.items():
                    out[(m.name, key)] = val
            return out


class Counter:
    def __init__(self, reg: MetricsRegistry, name: str, help_: str):
        self._m = reg._metric(name, help_, "counter")
        self._reg = reg

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = _labels_key(labels)
        with self._reg._lock:
            self._m.samples[key] = self._m.samples.get(key, 0.0) + amount


class Gauge:
    def __init__(self, reg: MetricsRegistry, name: str, help_: str):
        self._m = reg._metric(name, help_, "gauge")
        self._reg = reg

    def set(self, value: float, **labels) -> None:
        key = _labels_key(labels)
        with self._reg._lock:
            self._m.samples[key] = value

    def clear(self) -> None:
        with self._reg._lock:
            self._m.samples.clear()
