"""Synthetic BANK demo — first run of the ksa_bank archetype with note data through generate_master_fs.

HARD GATE first: confirm the synthetic SOFP BALANCES and the P&L is coherent (real net profit carrying
into OCI) BEFORE producing any document. If it does not balance / the P&L is degenerate, ABORT — never
generate on broken data. Then produce the PDF + Excel through the REAL path, and print a per-note tally
(note closing -> TB line -> match) plus the list of notes 'not generated' because their mechanism isn't
built yet.

    python scripts/bank_notes_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from ai_accountant.master_fs import generate_master_fs, load_master_store          # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TBF = ROOT / "tests" / "fixtures" / "bank_demo" / "bank_synthetic_tb.json"
GLF = ROOT / "tests" / "fixtures" / "bank_demo" / "bank_synthetic_gl.json"
OUT = ROOT / "exports"
DISCLAIMER = ("SYNTHETIC BANK DEMO — the trial balance AND the general ledger are INVENTED (not real, "
              "not Bank AlJazira's published statement). This proves the bank pipeline runs and the notes "
              "RECONCILE TO THE FACES; it is NOT verification against any published financial statement.")


def _stored(tb):
    rows = tb["rows"]
    return {"client": tb["client"], "master_id": "ksa_bank", "extensions": [],
            "tb": [{"account": r["account"], "label": r.get("label", r["concept_id"]),
                    "current": float(r["current"]), "prior": None} for r in rows],
            "mappings": [{"account": r["account"], "concept_id": r["concept_id"],
                          "client_label": r.get("label", r["concept_id"]), "provenance": "preparer"} for r in rows]}


def _line(model, st, cid):
    return next((l.current for l in model.statements[st] if l.concept_id == cid), None)


def hard_gate(store, stored) -> bool:
    """Build faces-only and confirm balance + a coherent P&L BEFORE any document is produced."""
    m = build_master_fs_export(store, stored, bank="synthetic bank demo")
    assets = _line(m, "balance_sheet", "bs_total_assets")
    liabeq = _line(m, "balance_sheet", "bs_total_liab_equity")
    ni = _line(m, "income_statement", "pl_net_income")
    tci = _line(m, "comprehensive_income", "oci_total_ci")
    oci = _line(m, "comprehensive_income", "oci_total_oci")
    diff = round(assets - liabeq, 2)
    bal_finding = [f for f in m.findings if str(f[0]) == "balance check"]
    print("=== HARD GATE (run BEFORE generating any document) ===")
    print(f"  SOFP: total assets {assets:,.0f}  ==  total liab+equity {liabeq:,.0f}   difference {diff:,.2f}")
    print(f"  P&L : net income for the year {ni:,.0f}")
    print(f"  OCI : other comprehensive income {oci:,.0f}  ->  total comprehensive income {tci:,.0f}")
    ok = True
    if diff != 0 or bal_finding:
        print(f"  ✗ SOFP DOES NOT BALANCE (diff {diff}; findings {bal_finding}) — ABORT, fix the TB."); ok = False
    if not ni or ni == 0:
        print("  ✗ P&L degenerate (net income 0) — ABORT."); ok = False
    if not tci or tci == ni:
        print("  ✗ OCI degenerate (carry adds nothing) — ABORT."); ok = False
    if ok:
        print("  ✓ GATE PASSED — SOFP balances (diff 0), net income real and carries into OCI. Safe to generate.")
    return ok


def gl_payloads(gl):
    sc = gl["sign_convention"]
    return {k: {"leaves": v["leaves"], "confirmed": v["confirmed"], "sign_convention": sc}
            for k, v in gl["notes"].items()}


def tally(model):
    print("\n=== PER-NOTE TALLY (note closing  vs  TB line value) ===")
    print(f"  {'note':<34}{'note closing':>14}{'TB line':>12}   match")
    for key, r in model.note_results.items():
        tbval = next((l.current for st in model.statements.values() for l in st if l.concept_id == key), None)
        if "note" in r:
            closing = r["note"].total_nbv
        else:
            closing = round(sum(r["split"]["portions"].values()), 2)
        match = (tbval is not None and abs(round(closing - tbval, 2)) < 0.005)
        cap = r.get("caption", key)
        print(f"  {cap[:33]:<34}{closing:>14,.2f}{(tbval or 0):>12,.0f}   {'Y' if match else 'N  <-- DOES NOT FOOT'}")
    notgen = [nv.note_ref for nv in model.note_views if nv.status == "not generated"]
    print("\n=== NOT GENERATED (mechanism not built / no GL) ===")
    for nv in model.note_views:
        if nv.status == "not generated":
            print(f"  {nv.note_ref}  —  {nv.caveats[0]}")
    return notgen


def main():
    tb = json.loads(TBF.read_text(encoding="utf-8"))
    gl = json.loads(GLF.read_text(encoding="utf-8"))
    store = load_master_store(seed_id="ksa_bank")
    stored = _stored(tb)

    if not hard_gate(store, stored):
        print("\nABORTED — broken data is not a deliverable. No document generated.")
        sys.exit(1)

    OUT.mkdir(exist_ok=True)
    res = generate_master_fs(stored, seed_id="ksa_bank", client=tb["client"], strategy="replay",
                             bank="synthetic bank demo", disclaimer=DISCLAIMER, gl=gl_payloads(gl),
                             write_to=str(OUT / "Master_FS_bank_synthetic_demo"))
    print(f"\nArchetype used: {res.master_id}  (must be ksa_bank)")
    tally(res.model)
    print(f"\nProduced: {OUT / 'Master_FS_bank_synthetic_demo'}.{{pdf,xlsx}}")


if __name__ == "__main__":
    main()
