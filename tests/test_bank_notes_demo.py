"""Synthetic BANK demo — guards the first ksa_bank run with notes through generate_master_fs.

Asserts the HARD GATE (SOFP balances, coherent P&L carrying into OCI), that the BANK archetype is used,
that each built note foots EXACTLY to its TB line, and that the unbuilt ECL/contra note renders honestly
as "not generated" (never forced through the roll-forward builder).

    python tests/test_bank_notes_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs import generate_master_fs, load_master_store          # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "tests" / "fixtures" / "bank_demo"


def _setup():
    tb = json.loads((BD / "bank_synthetic_tb.json").read_text(encoding="utf-8"))
    gl = json.loads((BD / "bank_synthetic_gl.json").read_text(encoding="utf-8"))
    store = load_master_store(seed_id="ksa_bank")
    stored = {"client": tb["client"], "master_id": "ksa_bank", "extensions": [],
              "tb": [{"account": r["account"], "label": r["concept_id"], "current": float(r["current"]),
                      "prior": None} for r in tb["rows"]],
              "mappings": [{"account": r["account"], "concept_id": r["concept_id"],
                            "client_label": r["concept_id"], "provenance": "preparer"} for r in tb["rows"]]}
    sc = gl["sign_convention"]
    payloads = {k: {"leaves": v["leaves"], "confirmed": v["confirmed"], "sign_convention": sc}
                for k, v in gl["notes"].items()}
    return store, stored, payloads


def _line(model, st, cid):
    return next((l.current for l in model.statements[st] if l.concept_id == cid), None)


def test_hard_gate_balances_and_pl_coherent():
    store, stored, _ = _setup()
    m = build_master_fs_export(store, stored, bank="synthetic bank demo")
    assert round(_line(m, "balance_sheet", "bs_total_assets")
                 - _line(m, "balance_sheet", "bs_total_liab_equity"), 2) == 0.0      # SOFP balances
    assert not [f for f in m.findings if str(f[0]) == "balance check"]               # no balance finding
    ni = _line(m, "income_statement", "pl_net_income")
    tci = _line(m, "comprehensive_income", "oci_total_ci")
    assert ni == 2200 and tci == 2440 and tci != ni                                  # real profit, carries into OCI


def test_bank_archetype_built_notes_foot_and_ecl_not_generated():
    store, stored, payloads = _setup()
    res = generate_master_fs(stored, seed_id="ksa_bank", client="synthetic-bank-demo", strategy="replay",
                             bank="synthetic bank demo", gl=payloads)
    m = res.model
    assert res.master_id == "ksa_bank"                                              # BANK, not telecom
    # every BUILT note foots EXACTLY to its TB line
    for key, r in m.note_results.items():
        if "note" in r:
            tbval = next(l.current for st in m.statements.values() for l in st if l.concept_id == key)
            assert abs(round(r["note"].total_nbv - tbval, 2)) < 0.005, (key, r["note"].total_nbv, tbval)
    assert m.note_status["bs_ppe"] == "BUILT" and m.note_status["bs_goodwill"] == "BUILT"
    # the financing+ECL note is NOT built (contra mechanism is a future slice) — honest, never faked. Instead of
    # an empty placeholder it now shows the figure(s) CARRIED TO THE FACE statement (plain lines), and says so.
    ecl = next(v for v in m.note_views if v.note_ref.startswith("Loans"))
    assert ecl.status == "not generated" and "contra_ecl" in ecl.caveats[0]
    face_vals = {round(l.current, 2) for st in m.statements.values() for l in st if l.current is not None}
    assert ecl.rows and all(r.kind == "line" and round(r.value, 2) in face_vals for r in ecl.rows)  # face figure, not faked
    assert any("face statement" in c for c in ecl.caveats)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"[pass] {name}")
            except AssertionError as exc:
                failures += 1; print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                import traceback; failures += 1; print(f"[ERROR] {name}: {exc}"); traceback.print_exc()
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
