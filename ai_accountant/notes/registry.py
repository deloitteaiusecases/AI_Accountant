"""Registry of note definitions. Add a NoteDefinition here to support a new note.

Today only Note 5 (Investments) is fully implemented. Other notes (loans, deposits, …) will be
added here with their own buckets/columns once we have sample data for each — see the Phase 6
plan. `DEFAULT_NOTE` keeps current single-note behavior unchanged.
"""
from __future__ import annotations

from ai_accountant.notes.definition import NoteDefinition

NOTE5 = NoteDefinition(
    note_id="note5",
    title="Note 5: Investments, Net",
    buckets=("FVTPL", "FVOCI", "Amortised Cost"),
    classification_map={
        "AC": "Amortised Cost",
        "FVOCI": "FVOCI",
        "FVOCI Equity": "FVOCI",
        "FVTPL": "FVTPL",
    },
    value_column="Carrying_Value_000",
    l1_label_map={
        "fvtpl": "FVTPL",
        "fvoci": "FVOCI",
        "amortised cost": "Amortised Cost",
        "amortized cost": "Amortised Cost",
        "total": "TOTAL",
    },
    gl_accounts={"103000": "FVTPL", "104000": "FVOCI", "105000": "Amortised Cost"},
)

NOTE_REGISTRY: dict[str, NoteDefinition] = {NOTE5.note_id: NOTE5}
DEFAULT_NOTE: NoteDefinition = NOTE5


def get_note(note_id: str = "note5") -> NoteDefinition:
    """Return the named note definition, falling back to the default."""
    return NOTE_REGISTRY.get(note_id, DEFAULT_NOTE)
