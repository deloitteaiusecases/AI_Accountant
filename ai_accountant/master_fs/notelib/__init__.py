"""notelib — the note-building machinery the seed engine reuses, relocated GL-free under master_fs.

These modules were formerly in `ai_accountant.fs_notes` (the GL "statement-first" pipeline). The seed
engine reused four pieces of them; they were copied here and severed from the GL-era dependencies
(`clarify`, `fs_notes.investments`, `face_tb`) so the GL packages can be deleted. Behaviour is frozen-
replay byte-identical (tests/test_notelib_frozen_replay.py).
"""
from __future__ import annotations

from ai_accountant.master_fs.notelib.movement import (ACCUM_CONTRA, COST, MovementNote, MovementSchedule,
                                                      MovementSection, build_movement_note)
from ai_accountant.master_fs.notelib.note import Note, NoteLine, Presentation
from ai_accountant.master_fs.notelib.ppe import PPENote, PPE_NOTE, build_ppe_note
from ai_accountant.master_fs.notelib.reference_codes import MovementConfig, movement_config

__all__ = ["ACCUM_CONTRA", "COST", "MovementNote", "MovementSchedule", "MovementSection",
           "build_movement_note", "Note", "NoteLine", "Presentation", "PPENote", "PPE_NOTE",
           "build_ppe_note", "MovementConfig", "movement_config"]
