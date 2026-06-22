"""Active-active global traffic director.

Models how the joined multi-cloud fleet behaves as ONE service: live user/service
traffic is distributed across ALL clouds at once (active-active), weighted by each
cloud's healthy serving capacity. When a cloud has an outage its weight collapses
to zero and the traffic is redistributed across the remaining clouds automatically
— then rebalances once it recovers. No cloud is a cold "backup".

This is the offline, testable model of two real mechanisms in this project's
deployment:
  * east-west (service->service): Istio multi-primary *global services* with
    locality-aware load balancing + outlier-detection failover (see mesh/).
  * north-south (user->app): a global GSLB / DNS load balancer health-checking all
    three cluster ingresses (see iac/terraform/modules/global_dns).
"""
from __future__ import annotations

from dataclasses import dataclass

from control_plane.models import NodeState


@dataclass
class Distribution:
    weights: dict[str, float]          # provider -> share of traffic (sums to ~1.0)
    allocation: dict[str, int]         # provider -> integer requests routed
    serving_clouds: list[str]          # clouds currently taking traffic
    drained_clouds: list[str]          # clouds excluded (outage / no capacity)


class GlobalTrafficDirector:
    """Computes active-active traffic distribution across clouds from live healthy
    capacity in the store. `down` models clouds whose health checks are failing
    (an outage) so their traffic is shed to the survivors."""

    def __init__(self, store, cluster: str):
        self.store = store
        self.cluster = cluster

    def capacity_by_cloud(self, down: set[str] | None = None) -> dict[str, int]:
        down = down or set()
        caps: dict[str, int] = {}
        for n in self.store.all_nodes():
            if n.cluster != self.cluster or n.state != NodeState.HEALTHY:
                continue
            if n.provider in down:
                continue
            caps[n.provider] = caps.get(n.provider, 0) + 1
        return caps

    def weights(self, down: set[str] | None = None) -> dict[str, float]:
        caps = self.capacity_by_cloud(down)
        total = sum(caps.values())
        if not total:
            return {}
        return {p: round(c / total, 4) for p, c in caps.items()}

    def distribute(self, requests: int, down: set[str] | None = None) -> Distribution:
        caps = self.capacity_by_cloud(down)
        total_cap = sum(caps.values())
        all_clouds = {n.provider for n in self.store.all_nodes()
                      if n.cluster == self.cluster}

        if not total_cap:
            return Distribution({}, {}, [], sorted(all_clouds))

        # proportional split with largest-remainder rounding so the integer
        # allocation always sums exactly to `requests`.
        exact = {p: requests * c / total_cap for p, c in caps.items()}
        alloc = {p: int(v) for p, v in exact.items()}
        remainder = requests - sum(alloc.values())
        for p in sorted(caps, key=lambda x: exact[x] - alloc[x], reverse=True):
            if remainder <= 0:
                break
            alloc[p] += 1
            remainder -= 1

        serving = sorted(caps)
        drained = sorted(all_clouds - set(caps))
        return Distribution(self.weights(down), alloc, serving, drained)
