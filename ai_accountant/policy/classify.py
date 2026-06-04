"""Classification engine: assign FVTPL / FVOCI / Amortised Cost to a security.

Hybrid strategy (from the project design):
  1. If the user uploaded an accounting policy, its extracted rules win (100% auditable).
  2. Otherwise fall back to built-in IFRS 9 inference heuristics.
Every decision carries a human-readable reason and its source ("policy" or "IFRS 9"), so the
classification is fully explainable / auditable.

This engine only runs for securities whose Classification is MISSING — when the data already
states a classification, the data is authoritative and is never overridden.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_accountant.ingestion.table_detect import DetectedTable

# Canonical buckets used across the app.
FVTPL, FVOCI, AC = "FVTPL", "FVOCI", "Amortised Cost"

# Columns we read a security's description from, in priority order.
_DESCRIPTION_COLS = ("Security_Name", "Security", "Asset_Type", "Instrument",
                     "Description", "Issuer")

# Only classify tables that actually carry a position/transaction value the cascade uses —
# this avoids classifying GL journals, EIR schedules, etc. that merely have a description column.
_VALUE_COLS = ("Carrying_Value_000", "Total_Cost_000", "Proceeds_000", "MtM_Change_000")


@dataclass
class ClassificationDecision:
    classification: str  # one of FVTPL / FVOCI / Amortised Cost
    reason: str
    source: str          # "policy" | "IFRS 9"


# IFRS 9 inference: ordered (keywords, classification, reason). First match wins.
_IFRS9_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("held for trading", "trading"), FVTPL,
     "Held for trading → FVTPL (IFRS 9 4.1.1)"),
    (("money market fund", "mutual fund", "fund units", "equity fund", "unit trust"), FVTPL,
     "Fund units → FVTPL (typically fail the SPPI test / held for trading)"),
    (("reit",), FVTPL, "REIT units → FVTPL (not an SPPI debt instrument)"),
    (("treasury bill", "t-bill", "sama bill", " bills", "discount note"), AC,
     "Short-term bills held to collect → Amortised Cost"),
    (("held to maturity", "hold to collect", "amortised", "amortized"), AC,
     "Hold-to-collect business model + SPPI → Amortised Cost"),
    (("share", "equity", "equities", "stock", "ordinary"), FVOCI,
     "Equity instrument, FVOCI election (not held for trading) (IFRS 9 5.7.5)"),
    (("sukuk", "bond", "note", "wakala", "debenture", "debt", "fixed rate", "floating rate"), FVOCI,
     "Debt instrument, hold-to-collect-and-sell business model → FVOCI"),
]


def normalize_classification(label: str) -> str:
    """Map any label spelling (FVIS, FVTPL, AC, Amortized Cost, …) to a canonical bucket."""
    l = str(label).strip().lower()
    if any(k in l for k in ("fvtpl", "fvis", "fair value through profit", "profit or loss",
                            "income statement", "held for trading")):
        return FVTPL
    if "fvoci" in l or "other comprehensive" in l:
        return FVOCI
    if "amort" in l or l == "ac":
        return AC
    return label  # leave unrecognized labels untouched


def classify(description: str, policy_rules: list[dict] | None = None) -> ClassificationDecision:
    """Classify one security by its description, policy first then IFRS 9 fallback."""
    desc = str(description).lower()

    # 1) Policy rules (authoritative when present).
    for rule in policy_rules or []:
        asset_type = str(rule.get("asset_type", "")).strip().lower()
        if asset_type and asset_type in desc:
            cls = normalize_classification(rule.get("classification", ""))
            reason = rule.get("reason") or f"Matches policy rule for '{asset_type}'"
            return ClassificationDecision(cls, reason, "policy")

    # 2) IFRS 9 inference.
    for keywords, cls, reason in _IFRS9_RULES:
        if any(k in desc for k in keywords):
            return ClassificationDecision(cls, reason, "IFRS 9")

    return ClassificationDecision(FVOCI, "Default — no specific rule matched (FVOCI)", "IFRS 9")


def apply_classification(
    tables: list["DetectedTable"], policy_rules: list[dict] | None = None,
) -> list[dict]:
    """Fill MISSING/blank `Classification` on any table that has a description column.

    Mutates tables in place (adds Classification + Classification_Source + Classification_Reason
    to the rows that lacked a class). Returns the audit trail of decisions made — existing
    classifications are left untouched (data is authoritative). No-op for fully-classified data
    like the bundled sample.
    """
    decisions: list[dict] = []
    for t in tables:
        desc_col = next((c for c in _DESCRIPTION_COLS if c in t.headers), None)
        if desc_col is None or not any(v in t.headers for v in _VALUE_COLS):
            continue
        has_class = "Classification" in t.headers
        needs = [r for r in t.records if not (has_class and str(r.get("Classification", "")).strip())]
        if not needs:
            continue

        for col in ("Classification", "Classification_Source", "Classification_Reason"):
            if col not in t.headers:
                t.headers.append(col)

        for rec in t.records:
            if str(rec.get("Classification", "")).strip():
                continue  # already classified -> keep
            d = classify(rec.get(desc_col, ""), policy_rules)
            rec["Classification"] = d.classification
            rec["Classification_Source"] = d.source
            rec["Classification_Reason"] = d.reason
            decisions.append({
                "security": rec.get(desc_col, ""),
                "classification": d.classification,
                "source": d.source,
                "reason": d.reason,
            })
    return decisions
