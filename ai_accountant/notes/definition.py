"""The NoteDefinition: all per-note configuration in one place.

A note is described by the buckets it rolls up into, how raw classification labels map to those
buckets, which column holds the value, how its FS-face lines are labelled (for reconciliation
against stated data), and which GL control accounts back each bucket (for the sub-ledger↔GL
control). Adding a new note = adding one of these to the registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteDefinition:
    note_id: str                                   # e.g. "note5"
    title: str                                     # e.g. "Note 5: Investments, Net"
    buckets: tuple[str, ...]                        # roll-up categories (excl. TOTAL)
    classification_map: dict[str, str]             # raw classification label -> bucket
    value_column: str = "Carrying_Value_000"       # the amount column aggregated to L1
    l1_label_map: dict[str, str] = field(default_factory=dict)   # FS-face label substr -> bucket/TOTAL
    gl_accounts: dict[str, str] = field(default_factory=dict)    # GL account code -> bucket

    @property
    def bucket_order(self) -> tuple[str, ...]:
        """Buckets plus the TOTAL line, in display order."""
        return (*self.buckets, "TOTAL")
