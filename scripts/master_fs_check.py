"""Phase-1 demo — GATE 0, then render a mapped TB against the master (populated subset) + comparatives.

    python scripts/master_fs_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                        # noqa: BLE001
    pass

from ai_accountant.master_fs.notelib.recon import FaceTB, TBAccount
from ai_accountant.master_fs import (ProvenanceStore, ClientMappingStore, load_master_store,
                                     record_preparer_mappings, render_comparative, render_master_fs,
                                     validate_csv, validate_seed)

SEEDS = ROOT / "seeds"


def _leaf(code, amount, caption):
    return TBAccount(code=code, level="L4", account_type="C", label=caption,
                     final_amount=float(amount), mapping=caption)


def main():
    print("=== GATE 0 — validate the seed against the approved xlsx ===")
    a = validate_seed(str(SEEDS / "master_fs_structure_seed.json"),
                      str(SEEDS / "Master_FS_Structure_Seed_AlJazira_SAAB.xlsx"))
    b = validate_csv(str(SEEDS / "master_fs_structure_seed.json"),
                     str(SEEDS / "master_fs_structure_seed.csv"))
    print(f"  SEED↔XLSX mismatches: {len(a)}   CSV↔JSON mismatches: {len(b)}   "
          f"→ {'FAITHFUL ✓' if not a and not b else 'MISMATCH — do not build'}")

    store = load_master_store(str(SEEDS / "master_fs_structure_seed.json"))
    print(f"  master concepts loaded: {len(store.concepts)} "
          f"(BS {len(store.statement('balance_sheet'))}, "
          f"income {len(store.statement('income_statement'))}, "
          f"OCI {len(store.statement('comprehensive_income'))})")

    # a small AlJazira TB (preparer-mapped by its own captions), current period
    cur = [_leaf("c_cash", 5_000, "Cash and balances with Saudi Central Bank (SAMA)"),
           _leaf("c_inv", 40_000, "Investments, net"),
           _leaf("c_loans", 120_000, "Financing, net"),
           _leaf("c_dep", -100_000, "Customer deposits")]
    fb = FaceTB(); fb.accounts.extend(cur)
    ms, au = ClientMappingStore(), ProvenanceStore()
    unmatched = record_preparer_mappings(fb, store, client_id="aljazira", mapping_store=ms, audit=au,
                                         approver="preparer", at="2026-06-11")
    print(f"\n=== Balance sheet (populated lines only, master order; provenance: preparer) ===")
    for l in render_master_fs(store, ms, "aljazira", {a.code: a.final_amount for a in cur}, "aljazira")["balance_sheet"]:
        print(f"  [{l.section:<11}] {l.label[:46]:<46} {l.amount:>14,.2f}")
    if unmatched:
        print(f"  (unmatched preparer captions, flagged not guessed: {unmatched})")

    # comparative: a prior-period TB of the SAME client
    prior = {"c_cash": 4_200, "c_inv": 38_000, "c_loans": 110_000, "c_dep": -92_000}
    print("\n=== Balance sheet — comparative (same client, two periods) ===")
    for r in render_comparative(store, ms, "aljazira", {a.code: a.final_amount for a in cur}, prior,
                                "aljazira", "balance_sheet"):
        c = f"{r.current:,.0f}" if r.current is not None else "—"
        p = f"{r.prior:,.0f}" if r.prior is not None else "—"
        print(f"  {r.label[:46]:<46} {c:>14}  {p:>14}")
    print("\nNOTE: the master holds STRUCTURE only — amounts live with the client's TB; only populated "
          "lines render; comparatives are two periods of the SAME client.")


if __name__ == "__main__":
    main()
