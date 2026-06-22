"""Rolling update: declare a new golden image for a pool; the reconciler rolls
the pool to it.

Strategy is replace-based (immutable infra) and — crucially — *level-triggered*:
`plan()` only records the new desired image as pool state. The reconciler then
drains stale-image nodes within the pool's `max_unavailable` budget every tick and
the scale-up path refills the gap with fresh nodes built from the new golden
image, until the whole pool is homogeneous. This is the same declarative,
restartable model used everywhere else in the system: one desired-state change,
driven to convergence by the control loop — not a script that must be re-run.
"""
from __future__ import annotations


def plan(store, cluster_name: str, pool_name: str, new_image: str) -> int:
    """Set the pool's desired golden image (a pure desired-state change) and
    persist it. The reconciler is what actually rolls the pool. Returns the number
    of live nodes still on the old image, i.e. the work the reconciler has left."""
    cluster = store.clusters[cluster_name]
    pool = cluster.pools[pool_name]
    pool.image_digest = new_image  # new desired golden image
    store.put_cluster(cluster)     # persist desired image (CLI store is file-backed)

    stale = [n for n in store.live_nodes_in_pool(cluster_name, pool_name)
             if n.image_digest != new_image]
    return len(stale)
