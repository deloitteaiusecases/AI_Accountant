"""Phase 6 tests: the NoteDefinition framework drives the engine (no hardcoded Note 5).

    python tests/test_notes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute import cascade  # noqa: E402
from ai_accountant.notes import NOTE5, NOTE_REGISTRY, NoteDefinition, get_note  # noqa: E402
from ai_accountant.validation import controls, reconcile  # noqa: E402


def test_registry_and_fallback():
    assert "note5" in NOTE_REGISTRY
    assert get_note("note5") is NOTE5
    assert get_note("does-not-exist") is NOTE5  # falls back to default


def test_note5_definition_shape():
    assert NOTE5.buckets == ("FVTPL", "FVOCI", "Amortised Cost")
    assert NOTE5.bucket_order == ("FVTPL", "FVOCI", "Amortised Cost", "TOTAL")
    assert NOTE5.classification_map["AC"] == "Amortised Cost"
    assert NOTE5.gl_accounts["103000"] == "FVTPL"
    assert "fvtpl" in NOTE5.l1_label_map


def test_engine_reads_from_definition_not_hardcoded():
    # The cascade / reconcile / controls now derive their note-specifics from NOTE5.
    assert cascade._BUCKETS == tuple(NOTE5.buckets)
    assert cascade._CLASS_MAP is NOTE5.classification_map
    assert reconcile._BUCKETS == NOTE5.bucket_order
    assert controls._GL_ACCOUNTS is NOTE5.gl_accounts


def test_a_new_note_can_be_defined():
    nd = NoteDefinition(
        note_id="note6",
        title="Note 6: Financing, Net",
        buckets=("Stage 1", "Stage 2", "Stage 3"),
        classification_map={"PERFORMING": "Stage 1"},
    )
    assert nd.note_id == "note6"
    assert nd.bucket_order == ("Stage 1", "Stage 2", "Stage 3", "TOTAL")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[pass] {name}")
            except AssertionError as exc:
                failures += 1
                print(f"[FAIL] {name}: {exc}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
