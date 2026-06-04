"""Note definitions — the seam that lets the engine generalize beyond Note 5.

Everything note-specific (buckets, classification mapping, value column, FS-face labels, GL
control accounts) lives in a `NoteDefinition`. The cascade / reconciliation / controls read
the active note's definition instead of hardcoding Note 5, so new notes plug in by adding a
definition to the registry (the path toward a full 40+-note financial statement).
"""
from ai_accountant.notes.definition import NoteDefinition
from ai_accountant.notes.registry import DEFAULT_NOTE, NOTE5, NOTE_REGISTRY, get_note

__all__ = ["NoteDefinition", "DEFAULT_NOTE", "NOTE5", "NOTE_REGISTRY", "get_note"]
