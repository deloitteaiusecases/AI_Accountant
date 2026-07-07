"""Slice SL-1d: three GUI-trustworthiness fixes so a user trusting the defaults isn't misled.

Fix 1 — the expense-sign heuristic proposes against each side's TARGET sign (expense target NEGATIVE), so a
positive-stored expense section proposes FLIP and a negative-stored one proposes AS_IS — the same detection
serves both conventions (the two-convention safety; NOT a hardcoded flip).
Fix 2 — the equity-residual line carries its OWN judgment kind ('estimated residual' from the seed), not the
hardcoded '(split)'.
Fix 3 — the Source-tag cross-check surfaces a conflict (the audit the GUI now runs at G2).

    python tests/test_sub_ledger_gui_trust.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.tb_ingest.sign import propose_tb_sign                    # noqa: E402
from ai_accountant.tb_ingest.source_route import source_routing_audit       # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                  # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export  # noqa: E402


def _prop(rows):
    return {s.section: s.proposed for s in propose_tb_sign(rows).sections}


# ============================================================ Fix 1 — expense-sign, BOTH conventions
def test_positive_stored_expense_proposes_flip():
    rows = [{"section": "Expense", "current": 8971028.0}, {"section": "Income", "current": -10778642.0},
            {"section": "Assets", "current": 165923974.0}]
    p = _prop(rows)
    assert p["Expense"] == "flip"            # stored POSITIVE (debit) → flip to presentation-NEGATIVE
    assert p["Income"] == "flip" and p["Assets"] == "as_is"


def test_negative_stored_expense_proposes_as_is_two_convention_safety():
    rows = [{"section": "Expense", "current": -2100.0}, {"section": "Income", "current": -4800.0},
            {"section": "Assets", "current": 9000.0}]
    p = _prop(rows)
    assert p["Expense"] == "as_is"           # stored NEGATIVE already (presentation sign) → NOT flipped
    assert p["Income"] == "flip"             # SAME detection: income stored negative → flip


def test_the_two_conventions_are_not_a_blanket_rule():
    # the SAME function gives OPPOSITE expense verdicts purely from the stored sign — proof it detects, not hardcodes
    assert _prop([{"section": "Expense", "current": 500.0}])["Expense"] == "flip"
    assert _prop([{"section": "Expense", "current": -500.0}])["Expense"] == "as_is"


def test_expense_and_income_are_distinct_sides():
    secs = {s.section: s.side for s in propose_tb_sign(
        [{"section": "Expense", "current": 1.0}, {"section": "Income", "current": -1.0}]).sections}
    assert secs["Expense"] == "expense" and secs["Income"] == "income"      # no longer lumped into one 'result'


# ============================================================ Fix 2 — finding-type-driven judgment kind
def _residual_model():
    store = load_master_store(seed_id="ksa_bank")
    tb = [{"account": "EQR", "label": "Combined balancing residual", "current": 2791092.0, "prior": 4170163.0,
           "section": "Equity", "maturity_hint": "Equity",
           "levels": ["Equity", "Equity", "Statutory reserve, retained earnings and treasury shares (net)",
                      "Combined balancing residual", ""]}]
    maps = [{"account": "EQR", "concept_id": "bs_equity_residual", "client_label": "x", "provenance": "preparer"}]
    return build_master_fs_export(store, {"client": "d", "master_id": store.master_id, "tb": tb, "mappings": maps,
                                          "extensions": []}, notes_attempted=True)


def test_residual_line_carries_estimated_residual_kind_not_split():
    m = _residual_model()
    assert m.judgment_kinds.get("bs_equity_residual") == "estimated residual"   # seed-declared, NOT '(split)'
    assert "split" not in m.judgment_kinds.get("bs_equity_residual", "")        # the residual never reads as a split


# ============================================================ Fix 3 — Source conflict audit (the GUI surface's source)
def test_source_audit_surfaces_a_conflict_for_the_gui():
    tb = [{"account": "a", "source_tag": "Note 99"}, {"account": "b", "source_tag": "Note 99"}]
    aud = source_routing_audit(tb, {"a": "bs_cash", "b": "bs_deposits"})
    assert aud["conflicts"] and aud["conflicts"][0]["concepts"] == ["bs_cash", "bs_deposits"]


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
