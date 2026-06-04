"""Typed schemas for profiles and the value-routing map.

These give the rest of the app (and the LLM's JSON output) a stable, validated shape.
Fleshed out as routing matures in Phase 2; Phase 0 defines the core types.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Level = Literal["L1", "L2", "L3", "L4"]


class TableProfile(BaseModel):
    """Lightweight profile of one detected table (never raw bulk rows)."""

    source_file: str
    sheet: str | None = None
    title: str | None = None
    headers: list[str] = Field(default_factory=list)
    sample_data: list[dict[str, Any]] = Field(default_factory=list)
    detected_level: Level | None = None  # filled by level detection (Phase 2)


class RoutingEntry(BaseModel):
    """One link in the routing map: which table/value feeds which note + calc."""

    source_file: str | None = None
    sheet: str | None = None
    table_title: str | None = None
    level: str | None = None          # "L1".."L4", "XREF", or None if unknown
    role: str = "unclassified"        # e.g. "sub-ledger holdings", "purchases"
    note: str = ""
    used_in_cascade: bool = False     # True if the cascade actually consumes this table
    confidence: str = "rule"          # "rule" (signature) or "ai" (model-classified)

    @property
    def origin(self) -> str:
        parts = [p for p in (self.source_file, self.sheet) if p]
        return " · ".join(parts) if parts else "(uploaded)"


class RoutingMap(BaseModel):
    """The full, user-reviewable routing map produced from profiles."""

    entries: list[RoutingEntry] = Field(default_factory=list)
    reasoning: str = ""

    def used(self) -> list[RoutingEntry]:
        return [e for e in self.entries if e.used_in_cascade]
