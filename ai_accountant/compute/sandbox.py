"""Guardrailed execution of AI-generated Pandas code.

Phase 0 decision: lightweight in-process guardrails now (import whitelist, no file/network
I/O, timeout); full subprocess/OS-level isolation deferred to Phase 7 (pre-deployment).

STATUS: stub — lands in Phase 1.
"""
from __future__ import annotations

import pandas as pd

# Only these names are allowed in generated code's namespace.
ALLOWED_IMPORTS = {"pandas", "numpy"}


def run_generated(code: str, data: pd.DataFrame) -> pd.DataFrame:
    """Execute `code` against `data` under guardrails and return the result frame."""
    raise NotImplementedError("Sandboxed execution lands in Phase 1.")
