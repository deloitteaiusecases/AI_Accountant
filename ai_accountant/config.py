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
# NOTE: if the GPT-5.x family requires the Responses API rather than chat.completions,
# adjust ai_accountant/llm/client.py — the model id is centralized here on purpose.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")


def get_api_key(explicit: str | None = None) -> str | None:
    """Resolve the OpenAI API key: explicit arg (e.g. from the UI) wins, else env."""
    return explicit or os.getenv("OPENAI_API_KEY")


# --- Paths -------------------------------------------------------------------
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
SAMPLE_NOTE5_CSV = SAMPLE_DATA_DIR / "AMNB_Note5_All_Levels.csv"

# --- Ingestion ---------------------------------------------------------------
PROFILE_SAMPLE_ROWS = 5  # rows per table shown to the LLM (never raw bulk data)

# --- Data hierarchy ----------------------------------------------------------
LEVELS = ("L1", "L2", "L3", "L4")  # L4 = raw transactions ... L1 = FS face

# --- Note 5 ground truth (SAR '000) — used to validate the cascade ----------
# From sample_data/AMNB_Note5_All_Levels.csv (AMNB FY2025).
NOTE5_GROUND_TRUTH = {
    "FVTPL": 2_780_000,
    "FVOCI": 12_350_000,
    "Amortised Cost": 9_680_000,
    "TOTAL": 24_810_000,
}
