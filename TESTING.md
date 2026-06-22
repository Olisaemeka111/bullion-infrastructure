# Testing Framework — cluster-infra

This project ships an extensive, dependency-free test framework built on the
Python standard library (`unittest`). It is organized into four tiers — **smoke**,
**unit**, **integration**, and **chaos/property** — plus shared fixtures and a set
of reusable **system invariants** that encode the design's safety guarantees.

> Zero third-party dependencies are required. Optional `pytest` / `coverage`
> integration is described at the end.

---

## 1. How to run

```bash
# fast suite: smoke + unit + integration + chaos (skips the 10K-node SLOW test)
python -m tests.run

# the fast 'does it turn on' gate (run this first / on every push)
python -m tests.run smoke

# a single tier
python -m tests.run unit
python -m tests.run integration
python -m tests.run chaos

# EVERYTHING, including the slow 10,000-node scale test
python -m tests.run all

# verbose
python -m tests.run -v unit

# plain stdlib discovery also works
python -m unittest discover -s tests
```

Current status: **80 tests** (79 fast + 1 slow), all green. Typical wall-clock:
smoke ≈ 0.05s, fast suite ≈ 0.3s, full `all` ≈ 1s. (The mini adds
`tests/unit/test_global_lb.py` — the active-active global traffic director.)

---

## 2. Test taxonomy

### 2.0 Smoke tests — `tests/smoke/` (fastest gate, run first)
Shallow critical-path checks that answer "does the system turn on?" in <0.1s.
If any fail, the deeper suites are not worth running.

| File | What it covers |
|---|---|
| `test_smoke.py` | every module imports; multi-cloud provision→HEALTHY; decommission empties; security gate admits only clean nodes; metrics + HTML dashboard produce output; the `clusterctl` CLI runs apply/reconcile/status/decommission; shipped artifacts (Grafana JSON, alerts, Atlantis, Argo, docs) exist and parse |

### 2.1 Unit tests — `tests/unit/` (fast, isolated, no control loop)
Exercise a single module in isolation; no reconciler, no provider fleet.

| File | Module under test | What it covers |
|---|---|---|
| `test_state_machine.py` | `control_plane/state_machine.py` | legal/illegal transitions, idempotent self-transition, forced-transition-needs-approver, terminal state |
| `test_models_store.py` | `control_plane/models.py`, `store.py` | unique ids, enum serialization, pool queries, revision bumps, live-node filtering, JSON persistence round-trip |
| `test_security.py` | `security/{policy,admission,rbac,hardening}.py` | provenance/attestation/hardening gate; PSS admission (restricted vs baseline); RBAC least-privilege; hardening baseline |
| `test_observability.py` | `observability/{metrics,telemetry}.py` | counter/gauge semantics, Prometheus exposition format, gauge collection from store |
| `test_networking.py` | `networking/fabric.py` | secure host-net defaults (Cilium/eBPF/mTLS/sFlow), provider primitive mapping, multi-NIC for GPU, cross-cloud private links |

### 2.2 Integration tests — `tests/integration/` (drive the full control loop)
Wire the real `Reconciler + Store + ProviderRegistry + Telemetry` together via
the `Env` fixture and run end-to-end scenarios.

| File | Scenario |
|---|---|
| `test_provisioning.py` | single-pool + multi-cloud/on-prem convergence, security gate on every healthy node, idempotency, scale up/down |
| `test_self_healing.py` | agent-reported failure replacement, heartbeat-timeout detection, full-capacity recovery, failure/heal metrics |
| `test_rolling_update.py` | all nodes reach new image, homogeneity preserved, `max_unavailable` never exceeded at any tick |
| `test_decommission.py` | whole-cluster teardown empties the store, nodes route through DRAINING, forced teardown requires approver |
| `test_orchestration.py` | Temporal-style bring-up + decommission workflows, homogeneity-verification activity catches drift |
| `test_scale.py` | mid-scale (700 nodes) convergence + the SLOW 10,000-node case |
| `test_observability.py` | Prometheus exposition reflects fleet, HTML dashboard renders, zero security rejections on a clean fleet |

### 2.3 Chaos / property tests — `tests/chaos/` (fault injection + randomized)
| File | What it does |
|---|---|
| `test_fault_injection.py` | injects 30–60% provider create failures and full-pool/single-provider outages; asserts the system still converges and never breaks invariants |
| `test_property_invariants.py` | 25 randomized, seeded cases generating sequences of scale/fail/update/tick ops against random fleets; asserts invariants after **every** step and convergence when left alone |

---

## 3. System invariants (the heart of the framework)

`tests/helpers.py::assert_system_invariants()` is callable from any integration
or chaos test and asserts the design's safety properties hold **after any
sequence of operations**:

1. **No leaked terminal nodes** — `TERMINATED` nodes are always garbage-collected.
2. **Secure-by-default** — every `HEALTHY` node passed the security gate, is
   attested, has a config hash, and owns an instance.
3. **Bounded blast radius** — per-pool concurrent destructive ops
   (`DRAINING`+`DECOMMISSIONING`) never exceed `max_unavailable` (except during an
   intentional whole-cluster decommission).

Plus targeted helpers: `assert_pool_at_desired()` and `assert_homogeneous()`.

This invariant-centric style is why the randomized property test is powerful: it
doesn't just check final state, it asserts the invariants at every intermediate
tick across thousands of random transitions.

---

## 4. Fixtures & builders (`tests/helpers.py`)

- `make_env(failure_rate=…, global_max_replacements=…)` → a fully-wired in-memory
  control plane (`Env`) with `apply / converge / tick / nodes / healthy` helpers.
- `pool(name, provider, count, …)` and `multicloud_pools(…)` → quick spec builders.
- Reproducibility: chaos cases use fixed seeds (`1000 + case`) printed in failure
  messages so any failure reproduces deterministically.

---

## 5. Markers & selection

- The 10K-node test is gated by `@unittest.skipUnless(CLUSTERINFRA_RUN_SLOW)` so
  the everyday suite stays sub-second; `python -m tests.run all` sets the env var.
- Tiers are selected by directory via the runner, so adding a test is just adding
  a file to the right folder — no registration needed.

---

## 6. CI

A ready-to-run GitHub Actions workflow ships at
[`.github/workflows/tests.yml`](.github/workflows/tests.yml). It runs on every
push and pull request across Python 3.11–3.13 (no third-party deps to install),
gating in order:

```yaml
- run: python -m tests.run smoke           # fastest gate, fail early
- run: python -m tests.run unit            # fast gate on every push
- run: python -m tests.run integration
- run: python -m tests.run chaos
- run: python -m tests.run all             # incl. the 10,000-node scale test
- run: python -m sim.simulate && python -m sim.multicloud && python -m sim.observe
```

---

## 7. Optional: pytest & coverage

The suite is plain `unittest`, so it runs unchanged under pytest if installed:

```bash
pip install pytest coverage
pytest tests/                                  # auto-discovers all tiers
coverage run -m tests.run all && coverage report -m
coverage html                                  # -> htmlcov/index.html
```

No code changes are required for either tool; they are purely additive.
