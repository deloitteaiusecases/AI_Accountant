"""Normalize foreign column names onto canonical fields.

Real uploads label the same concept many ways ("Acquisition Cost", "Cost", "Total_Cost_000").
This layer renames recognized aliases to the canonical names the cascade/routing expect, so the
downstream code stays simple and schema-agnostic. Unknown columns are left untouched (and can be
mapped by the optional AI layer in `routing.map_columns_with_ai`).

Design safety: canonical names map to themselves (identity), and only headers whose *normalized*
form exactly matches a known alias are renamed — so existing/foreign columns are never clobbered
by accident.
"""
from __future__ import annotations

import re

from ai_accountant.ingestion.table_detect import DetectedTable

# Canonical field -> list of alias spellings (free-form; normalized before matching).
_ALIASES: dict[str, list[str]] = {
    "Holding_ID": ["holding id", "holding", "security id", "instrument id", "position id",
                   "asset id", "lot id", "sec id", "investment id"],
    "Classification": ["classification", "class", "asset class", "category",
                       "measurement category", "ifrs category", "accounting classification"],
    "Carrying_Value_000": ["carrying value 000", "carrying value", "carrying amount",
                           "book value", "net carrying amount", "carrying"],
    "Total_Cost_000": ["total cost 000", "total cost", "cost", "purchase cost",
                       "acquisition cost", "consideration", "amount paid"],
    "Proceeds_000": ["proceeds 000", "proceeds", "sale proceeds", "disposal proceeds"],
    "Net_000": ["net 000", "net amount", "net income", "net receipt", "net"],
    "Income_Type": ["income type", "type of income", "income category"],
    "MtM_Change_000": ["mtm change 000", "mtm change", "mark to market change",
                       "fair value change", "revaluation change", "mtm"],
    "New_FV_000": ["new fv 000", "new fv", "new fair value", "updated fair value",
                   "closing fair value", "revalued fair value"],
    "Monthly_Amort_000": ["monthly amort 000", "monthly amort", "monthly amortisation",
                          "amortisation", "amortization", "eir amortisation", "amort"],
    "Opening_000": ["opening 000", "opening", "opening balance", "opening balance 000",
                    "opening carrying value", "brought forward", "b f"],
}


def _norm(header: str) -> str:
    """Lowercase and collapse non-alphanumerics to single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", str(header).lower()).strip()


def _build_reverse() -> dict[str, str]:
    rev: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        rev[_norm(canonical)] = canonical          # identity (preserve our own names)
        for alias in aliases:
            rev.setdefault(_norm(alias), canonical)
    return rev


_REVERSE = _build_reverse()


def canonical_for(header: str) -> str:
    """Return the canonical name for a header, or the header unchanged if unrecognized."""
    return _REVERSE.get(_norm(header), header)


def normalize_tables(tables: list[DetectedTable]) -> list[DetectedTable]:
    """Rename recognized headers (and record keys) to canonical names, in place."""
    for t in tables:
        mapping = {h: canonical_for(h) for h in t.headers}
        if all(k == v for k, v in mapping.items()):
            continue  # nothing to rename
        t.headers = [mapping[h] for h in t.headers]
        t.records = [{mapping.get(k, k): v for k, v in rec.items()} for rec in t.records]
    return tables
