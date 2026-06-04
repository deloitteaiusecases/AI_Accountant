"""Reconcile computed values against ground truth (the stated FS) / uploaded levels.

Conflict rule (Phase 0 decision): an UPLOADED level is authoritative (wins) over a computed
one. We still compute and surface the variance as a flag — never silently override.

Phase 1: reconcile computed L1 totals vs NOTE5_GROUND_TRUTH (`reconcile_l1`).
Phase 4: full **multi-level** reconciliation that compares the computed cascade against the
values STATED IN THE UPLOADED DATA at L1 (FS face) and L2 (classification summary), falling
back to config ground truth when a level isn't present in the upload.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from ai_accountant.config import NOTE5_GROUND_TRUTH

_BUCKETS = ("FVTPL", "FVOCI", "Amortised Cost", "TOTAL")


@dataclass
class ReconLine:
    item: str
    computed: float
    expected: float
    variance: float
    status: str  # "MATCH" | "VARIANCE"


@dataclass
class ReconSection:
    level: str          # e.g. "L1 — FS face", "L2 — classification summary"
    source: str         # "stated in uploaded data" | "ground truth (config)"
    lines: list[ReconLine] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return all(ln.status == "MATCH" for ln in self.lines)


def reconcile_l1(computed: dict[str, float], *, tolerance: float = 0.0) -> list[ReconLine]:
    """Compare computed L1 totals to the stated ground truth, line by line (Phase 1)."""
    lines: list[ReconLine] = []
    for item, expected in NOTE5_GROUND_TRUTH.items():
        c = float(computed.get(item, 0.0))
        variance = c - float(expected)
        status = "MATCH" if abs(variance) <= tolerance else "VARIANCE"
        lines.append(ReconLine(item, c, float(expected), variance, status))
    return lines


def all_match(lines: list[ReconLine]) -> bool:
    return all(line.status == "MATCH" for line in lines)


# --- Phase 4: multi-level reconciliation vs values stated in the data --------
def _num(cell) -> float | None:
    s = str(cell).strip().replace(",", "").replace("%", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _current_period_value(rec: dict, headers: list[str]) -> float | None:
    """Pick a row's current-period amount: prefer a 2025/'31 Dec' column, else first numeric."""
    skip = {"note", "gl code", "change", "change %", "ties to l1", "ties to l2"}
    for h in headers:
        if "2025" in h or "31 dec" in h.lower():
            v = _num(rec.get(h, ""))
            if v is not None:
                return v
    for h in headers:
        if h.lower() in skip:
            continue
        v = _num(rec.get(h, ""))
        if v is not None:
            return v
    return None


def _find(tables, *cols):
    for t in tables:
        if t.has_columns(*cols):
            return t
    return None


def _stated_l1(tables) -> dict[str, float] | None:
    """Stated L1 face buckets from a BS_Line table, if present."""
    t = _find(tables, "BS_Line")
    if t is None:
        return None
    label_map = {
        "fvtpl": "FVTPL", "fvoci": "FVOCI",
        "amortised cost": "Amortised Cost", "amortized cost": "Amortised Cost",
        "total": "TOTAL",
    }
    out: dict[str, float] = {}
    for rec in t.records:
        label = str(rec.get("BS_Line", "")).lower()
        for key, bucket in label_map.items():
            if key in label:
                v = _current_period_value(rec, t.headers)
                if v is not None:
                    out[bucket] = v
                break
    return out or None


def _stated_l2(tables) -> dict[str, float] | None:
    """Stated L2 bucket TOTALS from the 5.1 classification summary, if present."""
    t = _find(tables, "Classification", "Sub-Category")
    if t is None:
        return None
    out: dict[str, float] = {}
    for rec in t.records:
        sub = str(rec.get("Sub-Category", "")).strip().lower()
        cls = str(rec.get("Classification", "")).strip().lower()
        v = _current_period_value(rec, t.headers)
        if v is None:
            continue
        if "grand total" in cls or "grand total" in sub:
            out["TOTAL"] = v
        elif sub == "total":
            if "fvtpl" in cls or "fvis" in cls:
                out["FVTPL"] = v
            elif "fvoci" in cls:
                out["FVOCI"] = v
            elif "amort" in cls:
                out["Amortised Cost"] = v
    return out or None


def _section(level: str, source: str, computed: dict[str, float],
             stated: dict[str, float], tolerance: float = 0.0) -> ReconSection:
    lines = []
    for b in _BUCKETS:
        if b not in stated:
            continue
        c = float(computed.get(b, 0.0))
        var = c - float(stated[b])
        lines.append(ReconLine(b, c, float(stated[b]),
                               var, "MATCH" if abs(var) <= tolerance else "VARIANCE"))
    return ReconSection(level, source, lines)


def build_reconciliation(tables, computed_l1: dict[str, float]) -> list[ReconSection]:
    """Reconcile the computed L1 against the levels STATED IN THE UPLOADED DATA.

    Only includes a section when the corresponding level (L1 FS face / L2 classification summary)
    is actually present in the upload. For real L4-only uploads there is no stated level to
    reconcile against — that is expected, and trust comes from `controls.run_controls` instead.
    We deliberately do NOT compare against the bundled-sample's config ground truth here — that
    would meaninglessly compare a real upload to the AMNB sample's numbers.
    """
    sections: list[ReconSection] = []
    stated_l1 = _stated_l1(tables)
    if stated_l1:
        sections.append(_section("L1 — FS face (stated)", "stated in uploaded data",
                                 computed_l1, stated_l1))
    stated_l2 = _stated_l2(tables)
    if stated_l2:
        sections.append(_section("L2 — classification summary (stated)", "stated in uploaded data",
                                 computed_l1, stated_l2))
    return sections
