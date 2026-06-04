"""Generate Pandas transformation code from table profiles + the routing map.

The LLM writes code from PROFILES ONLY (never raw rows). Output is reviewable and executed
under guardrails (see sandbox.py).

STATUS: stub — lands in Phase 1 (L4->L3->L2->L1 for Note 5).
"""
from __future__ import annotations


def generate_cascade_code(level_from: str, level_to: str, profile: dict) -> str:
    """Return Pandas source that transforms `level_from` data into `level_to`."""
    raise NotImplementedError("Codegen lands in Phase 1.")
