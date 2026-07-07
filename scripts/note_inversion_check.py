"""Slice 5 demo — both notes against the REAL fixtures, showing the inverted contract.

Investments anchored to its TB line → reconciles → BUILT; a small lie (the breakdown ties internally
but ≠ the TB line) → BLOCKED with the Δ named; and the PARTIAL→BUILT transition when the unit is
confirmed. The derived TB ties by construction, so this proves breakdown↔line on real magnitudes —
NOT independent sign-off (that stays parked on finance's own TB).

    python scripts/note_inversion_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                        # noqa: BLE001
    pass

from test_note_inversion import (_facetb_and_gl_amounts, _investments_anchor,  # noqa: E402
                                 _investments_note)


def _show(tag, note, anchor):
    print(f"  {tag:<22} status={note.status():<8} reconciles_to_tb={note.reconciles_to_tb} "
          f"internal_ties={note.internal_structural_ties_ok} "
          f"anchor.gap={anchor.gap:,.2f} TB'000")
    for r in note.provisional_reasons():
        print(f"      reason: {r}")


def main():
    if not (ROOT / "TB" / "Derived_TB_From_GLs_XYZ.xlsx").exists():
        print("real TB/GL fixtures not present — skipping")
        return

    print("=== 1. Investments anchored to its TB line → reconciles → BUILT ===")
    facetb, gl = _facetb_and_gl_amounts()
    anchor = _investments_anchor(facetb, gl)
    note = _investments_note(anchor, unit_confirmed=True)
    _show("anchored, unit set", note, anchor)
    print(f"  total_net = {note.total_net:,.2f} SAR  ·  anchor TB raw = "
          f"{anchor.tb_recon_covered:,.2f} TB'000  ·  GL Σ = {anchor.gl_sum:,.2f} TB'000")

    print("\n=== 2. The internal-tie-that-lies — small Δ (~300k SAR) → BLOCKED, not waved through ===")
    facetb, gl = _facetb_and_gl_amounts()
    invleaf = next(l for l in facetb.amount_bearing_leaves() if l.mapping == "Investments")
    if invleaf.has_breakdown:                                          # 300 TB'000 = 300,000 SAR
        invleaf.raw_amount = round(invleaf.raw_amount + 300.0, 2)
    else:
        invleaf.final_amount = round(invleaf.final_amount + 300.0, 2)
    lie_anchor = _investments_anchor(facetb, gl)
    lie = _investments_note(lie_anchor, unit_confirmed=True)
    _show("internally ties, lies", lie, lie_anchor)

    print("\n=== 3. Recompile crosses a status boundary: unit unconfirmed → PARTIAL → answer → BUILT ===")
    facetb, gl = _facetb_and_gl_amounts()
    anchor = _investments_anchor(facetb, gl)
    before = _investments_note(anchor, unit_confirmed=False)
    after = _investments_note(anchor, unit_confirmed=True)
    print(f"  before (unit unanswered): {before.status()}   →   after (unit confirmed): {after.status()}")

    print("\nNOTE: derived TB ties by construction → proves breakdown↔line on real magnitudes, "
          "NOT independent sign-off (parked on finance's own TB).")


if __name__ == "__main__":
    main()
