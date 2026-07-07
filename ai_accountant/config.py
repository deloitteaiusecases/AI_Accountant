"""Central configuration for the AI Accountant app.

Values here are intentionally easy to change as the project evolves. Secrets come from the
environment (.env), never hardcoded.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present (no-op if missing).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Model -------------------------------------------------------------------
# The app's LLM. GPT-5.1 is the target model. Override via OPENAI_MODEL in .env.
# Pinned to the DATED SNAPSHOT, not the floating "gpt-5.1" alias: the alias silently resolves to
# whatever snapshot is current (it served "gpt-5.1-2025-11-13"), which would make AI proposals drift
# on re-run. A pinned snapshot makes classifications reproducible. Bump deliberately, never silently.
# NOTE: if the GPT-5.x family requires the Responses API rather than chat.completions,
# adjust ai_accountant/llm/client.py — the model id is centralized here on purpose.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1-2025-11-13")


def get_api_key(explicit: str | None = None) -> str | None:
    """Resolve the OpenAI API key: explicit arg (e.g. from the UI) wins, else env."""
    return explicit or OPENAI_API_KEY="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"
    
# (The legacy Note-5 cascade constants — SAMPLE_NOTE5_CSV / NOTE5_GROUND_TRUTH / PROFILE_SAMPLE_ROWS /
# LEVELS — were removed with the cascade. The seed-driven master-FS engine reads its L0–L4 structure from
# the trial balance and the archetype seed.)
