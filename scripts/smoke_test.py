"""Phase 0 smoke test.

Structural check (no API key needed): every package module imports cleanly and key
symbols are wired up. Run:  python scripts/smoke_test.py

If OPENAI_API_KEY is set (env or .env), also runs a tiny live GPT-5.1 JSON call.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check_imports() -> None:
    import ai_accountant  # noqa: F401
    from ai_accountant import config
    from ai_accountant.ingestion import profile_uploaded_files  # noqa: F401
    from ai_accountant.policy import extract_policy_rules, parse_policy_document  # noqa: F401
    from ai_accountant.routing import triage_files  # noqa: F401
    from ai_accountant.routing.models import RoutingMap, TableProfile  # noqa: F401
    from ai_accountant.llm.client import LLMClient  # noqa: F401

    assert config.OPENAI_MODEL, "OPENAI_MODEL not set"
    assert config.NOTE5_GROUND_TRUTH["TOTAL"] == 24_810_000
    # Pydantic models construct.
    TableProfile(source_file="x.csv", headers=["a"], sample_data=[{"a": 1}])
    RoutingMap()
    print(f"[ok] imports clean; model = {config.OPENAI_MODEL!r}")


def check_live_llm() -> None:
    from ai_accountant.config import get_api_key
    from ai_accountant.llm.client import LLMClient

    if not get_api_key():
        print("[skip] no OPENAI_API_KEY set — skipping live GPT-5.1 call")
        return
    client = LLMClient()
    out = client.complete_json('Return JSON: {"ping": "pong"}')
    print(f"[ok] live LLM call returned: {out}")


if __name__ == "__main__":
    check_imports()
    check_live_llm()
    print("Smoke test complete.")
