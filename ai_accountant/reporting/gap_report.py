"""Gap report (Phase 5) — the per-note BUILT / PARTIAL / BLOCKED status, rendered honestly.

The Phase-5 trap is that polish reads as completeness: a clean export of a PARTIAL note looks
finished in a way terminal output never did. So this report's contract is that **status, the
magnitude-unverified label, and the provisional outlook render at least as prominently as the
figures** — banners first, never a footnote. Every output channel (CLI now, Excel/PDF/UI later)
renders this one model; there is no second, prettier path that drops the caveats.

The per-note status model (`NoteStatus` + `note_status`) is duck-typed and GL-free; the master-FS render
model consumes it. The former CLI `GapReport` (which rendered a clarification queue) was part of the GL
"statement-first" pipeline and was removed with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteStatus:
    note_ref: str
    status: str                       # BUILT | PARTIAL | BLOCKED
    headline: str                     # the figure + the caveat that travels with it
    caveats: list[str] = field(default_factory=list)   # the prominent, must-read warnings
    reasons: list[str] = field(default_factory=list)   # the full provisional-reason list


def note_status(note) -> NoteStatus:
    """Adapt any FS-Gen note (Prepayments / Investments) to a uniform status, duck-typed."""
    reasons = list(note.provisional_reasons())
    caveats: list[str] = []
    if not getattr(note, "magnitude_verified", True):
        caveats.append(f"MAGNITUDE UNVERIFIED — {getattr(note, 'magnitude_label', '')}")
    if getattr(note, "provisional_outlook", ""):
        caveats.append(note.provisional_outlook)        # mixed case — a long all-caps line is hard to read
    return NoteStatus(
        note_ref=note.note_ref,
        status=note.status(),
        headline=note.status_line() if hasattr(note, "status_line") else note.status(),
        caveats=caveats,
        reasons=reasons,
    )


