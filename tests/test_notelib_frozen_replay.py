"""Slice 2 frozen-replay guard: relocating the note machinery GL-free must keep the seed engine's note
output BYTE-IDENTICAL. Generates the telecom notes (intangibles BUILT movement note, tc_ppe PARTIAL
multi-leaf movement note) through the REAL `generate_master_fs` path and compares a deterministic
serialization to a committed baseline. Any drift in a movement schedule, NBV, status, caveat, or rendered
row fails loud.

    python tests/test_notelib_frozen_replay.py            # asserts against the baseline
    python tests/test_notelib_frozen_replay.py --capture  # (re)writes the baseline (pre-relocation only)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs import generate_master_fs                              # noqa: E402
from ai_accountant.reporting.render_model import renderable, status_caption         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "regression"
BASELINE = FX / "notelib_telecom_baseline.json"
SIGN = {"accumulated_contra": "contra_negative", "disposals": "reduces_balance"}


def _gl_payloads():
    mf = json.loads((FX / "ppe_synthetic_gl_multileaf.json").read_text(encoding="utf-8"))
    it = json.loads((FX / "intangibles_synthetic_gl.json").read_text(encoding="utf-8"))
    ppe = {"leaves": mf["gl_leaves"], "confirmed": mf["confirmed"], "attribution": mf["attribution"],
           "sign_convention": SIGN}
    intang = {"leaves": it["leaves"], "confirmed": it["confirmed"], "sign_convention": SIGN}
    return mf, ppe, intang


def _stored(mf):
    cl = mf["concept_leaves"]
    tb = ([{"account": a, "label": f"PP&E {a}", "current": float(v), "prior": None} for a, v in cl.items()]
          + [{"account": "INT1", "label": "Intangibles", "current": 5800.0, "prior": None},
             {"account": "EQ1", "label": "Retained earnings", "current": -13250.0, "prior": None}])
    maps = ([{"account": a, "concept_id": "tc_ppe", "client_label": a, "provenance": "preparer"} for a in cl]
            + [{"account": "INT1", "concept_id": "tc_intangibles", "client_label": "Intangibles", "provenance": "preparer"},
               {"account": "EQ1", "concept_id": "tc_retained", "client_label": "Retained earnings", "provenance": "preparer"}])
    return {"client": "telco-demo", "master_id": "telecom_mobily", "tb": tb, "extensions": [], "mappings": maps}


def _gl(ppe, intang):
    return {"tc_ppe": ppe, "tc_intangibles": intang,
            "lease_liabilities": {"line_amounts": {"L_CUR": 1_213_068.0, "L_NC": 2_061_787.0},
                                  "classification": {"L_CUR": "current", "L_NC": "non_current"},
                                  "note_total": 3_274_855.0, "confirmed": True, "approver": "demo",
                                  "at": "2026-06-14"}}


def _snapshot() -> dict:
    """Deterministic serialization of every note the seed engine builds — statuses, captions, and the full
    renderable row grid (label + amount per row), which is what a movement schedule ultimately becomes."""
    mf, ppe, intang = _gl_payloads()
    model = generate_master_fs(_stored(mf), seed_id="telecom_mobily", client="telco-demo",
                               strategy="replay", gl=_gl(ppe, intang)).model
    out = {"note_status": dict(sorted(model.note_status.items())), "notes": []}
    for v in sorted(model.note_views, key=lambda v: v.note_ref):
        rows = [{"label": getattr(r, "label", ""), "amount": getattr(r, "value", getattr(r, "amount", None)),
                 "indent": getattr(r, "indent", 0)} for r in getattr(v, "rows", [])]
        out["notes"].append({"note_ref": v.note_ref, "status": v.status,
                             "caveats": list(getattr(v, "caveats", [])),
                             "reasons": list(getattr(v, "reasons", [])),
                             "caption": status_caption(v.status), "rows": rows})
    return out


def main(capture: bool) -> int:
    snap = _snapshot()
    blob = json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=True)
    if capture:
        BASELINE.write_text(blob, encoding="utf-8")
        print(f"[capture] wrote baseline: {BASELINE}  ({len(snap['notes'])} notes)")
        return 0
    if not BASELINE.exists():
        print(f"[ERROR] no baseline at {BASELINE} — run with --capture first")
        return 1
    want = BASELINE.read_text(encoding="utf-8")
    if blob == want:
        print(f"[pass] notelib frozen-replay byte-identical ({len(snap['notes'])} notes)")
        return 0
    print("[FAIL] notelib output DRIFTED from baseline")
    wl, gl = want.splitlines(), blob.splitlines()
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<eof>"
        g = gl[i] if i < len(gl) else "<eof>"
        if w != g:
            print(f"  line {i}: baseline={w!r}\n          now     ={g!r}")
            break
    return 1


if __name__ == "__main__":
    sys.exit(main("--capture" in sys.argv))
