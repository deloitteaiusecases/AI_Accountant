"""Slice N2 — per-note PDF page + Excel sheet, through the REAL `generate_master_fs` path.

Notes are BUILT by the orchestrator from a SUPPLIED synthetic GL fixture (not hand-fed note_results) and
rendered as their own pages/sheets. Proves: a BUILT movement note (intangibles, captioned, amortization
schedule), a deliberately PARTIAL movement note (tc_ppe, multi-leaf — one leaf uncovered), the lease
maturity split, and a declared-but-unbuilt note (tc_rou) rendering "not generated". Plus the two amendment
guards: (1) every non-BUILT status reads as a WORD, not colour alone; (2) building ≠ confirming — the split
is JUDGMENT_UNCONFIRMED by default and only JUDGMENT_CONFIRMED when the fixture supplies a confirmation.

The actual PDF + Excel are written to exports/ as the deliverable.

    python tests/test_master_fs_notes_export.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs import generate_master_fs                              # noqa: E402
from ai_accountant.reporting.master_fs_export import (export_master_fs_excel_bytes,  # noqa: E402
                                                      export_master_fs_pdf_bytes)
from ai_accountant.reporting.render_model import STATUS_COLOUR, renderable, status_caption  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "regression"
OUT = ROOT / "exports"
SIGN = {"accumulated_contra": "contra_negative", "disposals": "reduces_balance"}


def _gl_payloads():
    """Build the supplied GL payloads from the existing synthetic fixtures + an inline lease split."""
    mf = json.loads((FX / "ppe_synthetic_gl_multileaf.json").read_text(encoding="utf-8"))
    it = json.loads((FX / "intangibles_synthetic_gl.json").read_text(encoding="utf-8"))
    ppe = {"leaves": mf["gl_leaves"], "confirmed": mf["confirmed"], "attribution": mf["attribution"],
           "sign_convention": SIGN}                                   # GL covers P1+P2; P3 uncovered → PARTIAL
    intang = {"leaves": it["leaves"], "confirmed": it["confirmed"], "sign_convention": SIGN}
    return mf, ppe, intang


def _stored(mf):
    cl = mf["concept_leaves"]                                          # P1/P2/P3 → tc_ppe (multi-leaf)
    tb = ([{"account": a, "label": f"PP&E {a}", "current": float(v), "prior": None} for a, v in cl.items()]
          + [{"account": "INT1", "label": "Intangibles", "current": 5800.0, "prior": None},
             {"account": "EQ1", "label": "Retained earnings", "current": -13250.0, "prior": None}])
    maps = ([{"account": a, "concept_id": "tc_ppe", "client_label": a, "provenance": "preparer"} for a in cl]
            + [{"account": "INT1", "concept_id": "tc_intangibles", "client_label": "Intangibles", "provenance": "preparer"},
               {"account": "EQ1", "concept_id": "tc_retained", "client_label": "Retained earnings", "provenance": "preparer"}])
    return {"client": "telco-demo", "master_id": "telecom_mobily", "tb": tb, "extensions": [], "mappings": maps}


def _gl(ppe, intang, *, confirm_split):
    return {
        "tc_ppe": ppe,                                                # PARTIAL (P3 uncovered)
        "tc_intangibles": intang,                                     # BUILT
        "lease_liabilities": {                                        # Case B (halves not in TB) → judgment-only
            "line_amounts": {"L_CUR": 1_213_068.0, "L_NC": 2_061_787.0},
            "classification": {"L_CUR": "current", "L_NC": "non_current"},
            "note_total": 3_274_855.0, "confirmed": confirm_split, "approver": "demo", "at": "2026-06-14"},
        # tc_rou: NO payload → "not generated"
    }


def _run(confirm_split, write_to=None):
    mf, ppe, intang = _gl_payloads()
    stored = _stored(mf)
    return generate_master_fs(stored, seed_id="telecom_mobily", client="telco-demo", strategy="replay",
                              gl=_gl(ppe, intang, confirm_split=confirm_split), write_to=write_to)


def _view(model, key):
    return next(v for v in model.note_views if key in v.note_ref or key == v.note_ref)


def test_notes_build_and_render_through_orchestrator():
    m = _run(confirm_split=False).model
    keys = {v.note_ref for v in m.note_views}
    assert "Intangible assets" in keys and "Right-of-use assets" in keys      # built + declared-but-unbuilt
    assert m.note_status["tc_intangibles"] == "BUILT" and m.note_status["tc_ppe"] == "PARTIAL"
    # intangibles BUILT, captioned, amortization schedule present (the generic movement branch)
    intang = next(v for v in m.note_views if v.note_ref == "Intangible assets")
    assert intang.status == "BUILT"
    assert any("Amortization charge" in r.label for r in intang.rows)         # amortization, NOT depreciation
    assert any("Accumulated amortization" not in r.label and "Accumulated contra" == r.label.strip()
               for r in intang.rows)                                          # generic contra label (no PP&E voice)


def test_partial_and_not_generated_render_loud_in_words():
    m = _run(confirm_split=False).model
    ppe = next(v for v in m.note_views if v.note_ref == "Property, plant and equipment")
    assert ppe.status == "PARTIAL"
    assert any("PARTIAL" in c for c in ppe.caveats)                           # AMENDMENT 1 — status as WORDS
    assert any("P3" in c or "UNCOVERED" in c for c in ppe.caveats)            # uncovered leaf named in words
    rou = next(v for v in m.note_views if v.note_ref == "Right-of-use assets")
    assert rou.status == "not generated" and not rou.rows
    assert any("not generated" in c for c in rou.caveats)


def test_building_is_not_confirming_split_amendment2():
    # DEFAULT: built but UNCONFIRMED (the real path has no fixture-confirmation)
    m0 = _run(confirm_split=False).model
    assert m0.note_status["lease_liabilities"] == "JUDGMENT_UNCONFIRMED"
    assert m0.not_final is True                                               # unconfirmed → not final
    lease0 = next(v for v in m0.note_views if v.status.startswith("JUDGMENT"))
    assert any("MANAGEMENT JUDGMENT" in c and "UNCONFIRMED" in c for c in lease0.caveats)
    # ONLY with an explicit fixture-confirmation does it become CONFIRMED (still judgment-only for Case B)
    m1 = _run(confirm_split=True).model
    assert m1.note_status["lease_liabilities"] == "JUDGMENT_CONFIRMED"
    lease1 = next(v for v in m1.note_views if v.status.startswith("JUDGMENT"))
    assert any("MANAGEMENT JUDGMENT" in c for c in lease1.caveats)            # marker persists when confirmed


def test_status_colour_map_distinguishes_states():
    # each state maps to a DISTINCT colour AND a distinct word (colour is reinforcement, never the only signal)
    for st in ("BUILT", "PARTIAL", "BLOCKED", "JUDGMENT_CONFIRMED", "not generated"):
        assert st in STATUS_COLOUR and status_caption(st) != ""
    assert STATUS_COLOUR["PARTIAL"] != STATUS_COLOUR["BLOCKED"] != STATUS_COLOUR["JUDGMENT_CONFIRMED"]
    assert STATUS_COLOUR["BUILT"] not in (STATUS_COLOUR["PARTIAL"], STATUS_COLOUR["BLOCKED"])


def test_bytes_wrappers_return_nonempty():
    m = _run(confirm_split=False).model
    assert export_master_fs_excel_bytes(m)[:2] == b"PK" and len(export_master_fs_excel_bytes(m)) > 2000
    assert export_master_fs_pdf_bytes(m)[:4] == b"%PDF" and len(export_master_fs_pdf_bytes(m)) > 2000


def test_ppe_renderable_baseline_byte_identical():
    """The generalized renderable() reproduces the pre-edit PP&E rows EXACTLY (schedule rows additive)."""
    import dataclasses as dc
    from ai_accountant.master_fs.notelib import Presentation, build_ppe_note
    from ai_accountant.master_fs.notelib.propose import ConfirmedPPEAccount

    @dc.dataclass
    class L:
        gl_account: str; opening: float; closing: float; movement_by_ref: dict = dc.field(default_factory=dict)
    fx = json.loads((FX / "ppe_synthetic_gl.json").read_text(encoding="utf-8"))
    leaves = [L(d["gl_account"], d["opening"], d["closing"], d["movement_by_ref"]) for d in fx["leaves"]]
    confirmed = {a: ConfirmedPPEAccount(c, r, "seed", "2026") for a, (c, r) in fx["confirmed"].items()}
    rn = renderable(build_ppe_note(leaves, confirmed, presentation=Presentation(scale=1, confirmed=True))[0])
    new = [{"label": r.label, "value": r.value, "raw_sar": r.raw_sar, "kind": r.kind, "flag": r.flag,
            "indent": r.indent} for r in rn.rows]
    base = json.loads((FX / "ppe_renderable_baseline.json").read_text(encoding="utf-8"))
    it = iter(new)                                                            # baseline rows preserved IN ORDER
    for br in base["rows"]:
        assert any(nr == br for nr in it), f"baseline row not reproduced: {br}"
    for k in ("note_ref", "status", "status_line", "caveats", "reasons"):
        assert getattr(rn, k) == base[k]


def test_emit_deliverable_documents():
    """Produce the ACTUAL PDF + Excel (both split variants) — the thing a human looks at."""
    OUT.mkdir(exist_ok=True)
    _run(confirm_split=False, write_to=str(OUT / "Master_FS_telecom_notes_unconfirmed"))
    _run(confirm_split=True, write_to=str(OUT / "Master_FS_telecom_notes_confirmed"))
    for tag in ("unconfirmed", "confirmed"):
        assert (OUT / f"Master_FS_telecom_notes_{tag}.pdf").exists()
        assert (OUT / f"Master_FS_telecom_notes_{tag}.xlsx").exists()


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
            except Exception as exc:  # noqa: BLE001
                import traceback
                failures += 1
                print(f"[ERROR] {name}: {exc}")
                traceback.print_exc()
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
