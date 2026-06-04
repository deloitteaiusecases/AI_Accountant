"""LLM-driven and rule-based routing.

The routing map answers the core question: given a pile of heterogeneous tables (across many
files/sheets, at any level), *what is each table and which note/calculation does it feed?*

`build_routing_map` is deterministic (column-signature based) so it runs with no API key and is
fully testable. `enrich_routing_map_with_ai` optionally asks GPT-5.1 to classify tables the
rules couldn't (unknown schemas) — it never blocks the deterministic result.
"""
from __future__ import annotations

import json
from typing import Any

from ai_accountant.ingestion.table_detect import DetectedTable, detect_level
from ai_accountant.llm.client import LLMClient
from ai_accountant.routing.models import RoutingEntry, RoutingMap

# Role detection by column signature. Order matters (first match wins).
_ROLE_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("opening balances", ("Classification", "Opening_000")),
    ("sub-ledger holdings", ("Holding_ID", "Carrying_Value_000")),
    ("purchases", ("Total_Cost_000",)),
    ("sales/maturities", ("Proceeds_000",)),
    ("coupon/dividend income", ("Income_Type", "Net_000")),
    ("mark-to-market revaluation", ("MtM_Change_000",)),
    ("EIR amortisation", ("Monthly_Amort_000",)),
    ("ECL by security", ("ECL_000",)),
    ("GL journal entries", ("JE_ID",)),
    ("classification summary", ("Classification", "Sub-Category")),
    ("movement schedule", ("Movement", "FVTPL")),
    ("income analysis", ("Income Source",)),
    ("fair value hierarchy", ("FVOCI Debt",)),
    ("ECL summary", ("Stage", "Gross Exposure")),
    ("cross-reference map", ("From_Level", "To_Level")),
    ("FS face — balance sheet", ("BS_Line",)),
    ("FS face — P&L", ("P&L_Line",)),
    ("FS face — OCI", ("OCI_Line",)),
    ("FS face — equity", ("Equity_Line",)),
]

# Which roles the deterministic cascade actually consumes.
_USED_ROLES = {
    "opening balances", "sub-ledger holdings", "purchases", "sales/maturities",
    "coupon/dividend income", "mark-to-market revaluation", "EIR amortisation",
}


def detect_role(table: DetectedTable) -> str:
    for role, cols in _ROLE_SIGNATURES:
        if table.has_columns(*cols):
            return role
    return "unclassified"


def build_routing_map(tables: list[DetectedTable], note: str = "Note 5: Investments") -> RoutingMap:
    """Classify every table by level + role (rule-based). No API key required."""
    entries: list[RoutingEntry] = []
    for t in tables:
        role = detect_role(t)
        entries.append(RoutingEntry(
            source_file=t.source_file,
            sheet=t.sheet,
            table_title=t.title,
            level=t.level or detect_level(t),
            role=role,
            note=note if role in _USED_ROLES else "",
            used_in_cascade=role in _USED_ROLES,
            confidence="rule",
        ))
    return RoutingMap(entries=entries, reasoning="Classified by column signature.")


def enrich_routing_map_with_ai(
    tables: list[DetectedTable], routing: RoutingMap, api_key: str, note: str = "Note 5: Investments",
) -> RoutingMap:
    """Ask GPT-5.1 to classify tables the rules left 'unclassified' (unknown schemas).

    Sends only profiles (headers + a couple of sample rows), never bulk data. Best-effort:
    on any error the deterministic map is returned unchanged.
    """
    unknown = [(i, t) for i, (e, t) in enumerate(zip(routing.entries, tables))
               if e.role == "unclassified"]
    if not unknown:
        return routing

    profiles = {
        f"{i}": {
            "origin": t.origin,
            "headers": t.headers,
            "sample": t.records[:2],
        } for i, t in unknown
    }
    prompt = f"""
You are routing accounting data to build '{note}'. For each table below (keyed by index),
classify its hierarchy level and role. Levels: L4 (raw transactions), L3 (sub-ledger holdings),
L2 (note disclosure tables), L1 (financial-statement face lines).

Return strictly JSON:
{{ "classifications": {{ "<index>": {{"level": "L4", "role": "short description"}} }} }}

Tables (headers + sample rows only):
{json.dumps(profiles, indent=2, default=str)}
"""
    try:
        out = LLMClient(api_key=api_key).complete_json(prompt)
        cls = out.get("classifications", {})
        for key, info in cls.items():
            idx = int(key)
            if 0 <= idx < len(routing.entries):
                routing.entries[idx].level = info.get("level") or routing.entries[idx].level
                routing.entries[idx].role = info.get("role") or routing.entries[idx].role
                routing.entries[idx].confidence = "ai"
    except Exception:  # noqa: BLE001 - AI enrichment is optional
        pass
    return routing


# --- AI column mapping for truly foreign schemas ------------------------------
# Canonical fields the cascade understands, with plain-language meaning for the model.
CANONICAL_FIELDS: dict[str, str] = {
    "Holding_ID": "unique identifier of an individual security / holding / position",
    "Classification": "IFRS measurement class (FVTPL or FVIS, FVOCI, Amortised Cost)",
    "Carrying_Value_000": "carrying / book value of a holding, in thousands",
    "Total_Cost_000": "total purchase / acquisition cost of a buy transaction, in thousands",
    "Proceeds_000": "sale or maturity proceeds, in thousands",
    "Net_000": "net income amount received (coupon/dividend), in thousands",
    "Income_Type": "kind of income: coupon, dividend, or distribution",
    "MtM_Change_000": "mark-to-market / fair-value change for the period, in thousands",
    "New_FV_000": "updated fair value after a revaluation, in thousands",
    "Monthly_Amort_000": "EIR (effective-interest) amortisation amount, in thousands",
}


def map_columns_with_ai(
    headers: list[str], sample_rows: list[dict[str, Any]], api_key: str,
) -> dict[str, str]:
    """Ask GPT-5.1 to map a table's (foreign) headers onto canonical fields.

    Returns {actual_header: canonical_field} only for confident matches. Profiles only —
    headers + a couple of sample rows, never bulk data.
    """
    fields_doc = "\n".join(f"  - {k}: {v}" for k, v in CANONICAL_FIELDS.items())
    prompt = f"""
Map this table's columns onto the canonical accounting fields below. Only map a column when
you are confident it means the same thing; otherwise omit it (do NOT force a match).

Canonical fields:
{fields_doc}

Table headers: {json.dumps(headers)}
Sample rows (for context only): {json.dumps(sample_rows[:2], default=str)}

Return strictly JSON:
{{ "mapping": {{ "<actual header>": "<canonical field>" }} }}
Include only confident mappings. If none, return {{ "mapping": {{}} }}.
"""
    out = LLMClient(api_key=api_key).complete_json(prompt)
    mapping = out.get("mapping", {})
    # Keep only mappings whose target is a real canonical field.
    return {h: c for h, c in mapping.items() if c in CANONICAL_FIELDS}


def ai_normalize_tables(tables: list[DetectedTable], api_key: str) -> list[DetectedTable]:
    """For tables the rules can't classify, use AI column mapping to canonicalize headers.

    Best-effort and key-gated: any failure leaves the table unchanged. Lets genuinely foreign
    schemas (unknown column names) feed the cascade once their columns are mapped.
    """
    for t in tables:
        if detect_role(t) != "unclassified":
            continue  # already understood by signature
        try:
            mapping = map_columns_with_ai(t.headers, t.records, api_key)
        except Exception:  # noqa: BLE001 - AI mapping is optional
            continue
        if not mapping:
            continue
        t.headers = [mapping.get(h, h) for h in t.headers]
        t.records = [{mapping.get(k, k): v for k, v in rec.items()} for rec in t.records]
    return tables


# --- back-compat: original file-level triage (still used by older callers) ----
def triage_files(
    api_key: str,
    file_profiles: dict[str, dict[str, Any]],
    target_note: str = "Note 5: Investments",
) -> dict[str, Any]:
    """Ask the model which file(s) contain the L4 data needed to build `target_note`."""
    profiles_str = json.dumps(file_profiles, indent=2, default=str)
    prompt = f"""
You are an intelligent data router for an AI Accountant application.
Your goal is to generate '{target_note}'.

Given the file profiles (filenames, headers, sample rows) below, which file(s) contain the
lowest-level transactional data (L4) needed to aggregate {target_note}? Look for columns
related to purchases, sales, coupons, mark-to-market (MTM), and expected credit loss (ECL).

Return strictly JSON:
{{ "selected_files": ["filename1.csv"], "reasoning": "why" }}

File Profiles:
{profiles_str}
"""
    return LLMClient(api_key=api_key).complete_json(prompt)
