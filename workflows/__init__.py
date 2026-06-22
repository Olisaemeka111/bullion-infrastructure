"""Idempotent, restartable lifecycle workflows (Temporal / Argo analog).

Each function advances a node by at most one stage per call and is safe to call
again from any state, so the level-triggered reconciler can drive them every tick
and a crash mid-workflow simply resumes on the next tick.
"""
