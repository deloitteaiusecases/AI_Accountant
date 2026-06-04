"""Use the LLM to turn raw policy text into concrete classification mapping rules.

Migrated from the old engine.py; now routed through the shared LLMClient (GPT-5.1).
"""
from __future__ import annotations

from typing import Any

from ai_accountant.llm.client import LLMClient

# Policy text can be long; cap what we send to stay within reasonable token budgets.
_MAX_POLICY_CHARS = 15_000


def extract_policy_rules(api_key: str, policy_text: str) -> dict[str, Any]:
    """Extract asset-type -> classification rules (FVTPL/FVOCI/Amortised Cost) as JSON."""
    prompt = f"""
You are an expert financial accountant. The following is a raw text excerpt from a bank's
Accounting Policies document. Extract the concrete rules on how various investment assets
should be classified (e.g., FVTPL, FVOCI, Amortised Cost).

Return the result strictly as JSON:
{{
    "mapping_rules": [
        {{"asset_type": "example", "classification": "FVTPL", "reason": "held for trading"}}
    ]
}}

Policy Text:
{policy_text[:_MAX_POLICY_CHARS]}
"""
    client = LLMClient(api_key=api_key)
    return client.complete_json(prompt)
