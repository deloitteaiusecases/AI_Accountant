"""Slice SL-1b: route P&L/OCI + the cheap gaps so the FULL faces balance on the real bank TB.

Two layers:
  * ENGINE-LEVEL guards (no file) — the router fixes that made the full TB resolve correctly:
    cross-statement guard (a P&L row's instrument label must NOT route onto the balance sheet); L0 is
    authoritative (an FVOCI *investment* / an equity '…OCI…' reserve stay on the balance sheet); the
    combined L2—L3 key disambiguates an OCI movement; the seed-declared residual caveat renders a
    face-visible marker; a conceptless OCI movement FLAGS, never forced.
  * REAL-FILE end-to-end (skipped if `Draft Data for working.xlsx` is absent) — the milestone: the SOFP
    BALANCES both years (PP&E alias + the equity residual), the income statement foots, OCI foots for the
    aliasable movements, and only the 3 genuinely-conceptless OCI rows remain flagged.

    python tests/test_sub_ledger_full_balance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.seed import load_master_store                  # noqa: E402
from ai_accountant.tb_ingest.resolve import resolve_row, _statement_from_levels  # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "Draft Data for working.xlsx"


def _row(section, l2, l3, **kw):
    return {"account": kw.get("account", "x"), "label": l3 or l2, "section": section,
            "maturity_hint": f"{section} - NC/C", "levels": [section, kw.get("l1", f"{section} - NC/C"), l2, l3, ""]}


# ============================================================ router guards (no file)
def test_statement_from_levels_l0_authoritative():
    assert _statement_from_levels(["Income", "Funded Income", "x", "y"]) == "income_statement"
    assert _statement_from_levels(["Assets", "", "Investments, net", "Held at FVOCI"]) == "balance_sheet"   # FVOCI ≠ OCI
    assert _statement_from_levels(["Equity", "", "Other reserves", "Share in OCI of an associate"]) == "balance_sheet"
    assert _statement_from_levels(["Income", "Other Comprehensive", "Cash flow hedges", "x"]) == "comprehensive_income"


def test_cross_statement_guard_pl_row_does_not_route_onto_balance_sheet():
    store = load_master_store(seed_id="ksa_bank")
    # a P&L income row whose L3 instrument label "Financing" matches the bs_loans alias — must NOT land on the BS
    c, _ = resolve_row(store, _row("Income", "Net special commission income", "Financing", l1="Funded Income"))
    assert c is None or c.statement == "income_statement"


def test_l0_primacy_fvoci_investment_stays_on_balance_sheet():
    store = load_master_store(seed_id="ksa_bank")
    c, _ = resolve_row(store, _row("Assets", "Investments, net", "Held at FVOCI"))
    assert c is not None and c.concept_id == "bs_investments"          # not mis-sent to OCI by the 'oci' in 'FVOCI'


def test_combined_key_disambiguates_ambiguous_oci_movement():
    store = load_master_store(seed_id="ksa_bank")
    debt, _ = resolve_row(store, _row("Income", "Fair value reserve - FVOCI debt", "Net change in fair value",
                                      l1="Other Comprehensive"))
    eq, _ = resolve_row(store, _row("Income", "Fair value reserve - FVOCI equity", "Net change in fair value",
                                    l1="Other Comprehensive"))
    assert debt is not None and debt.concept_id == "oci_fvoci_debt"     # same L3, disambiguated by the L2 reserve
    assert eq is not None and eq.concept_id == "oci_fvoci_eq"


def test_conceptless_oci_movement_flags_not_forced():
    store = load_master_store(seed_id="ksa_bank")
    c, _ = resolve_row(store, _row("Income", "Employee share-based plan reserve", "Movement during the year",
                                   l1="Other Comprehensive"))
    assert c is None                                                    # no near-miss concept → flag (never forced)


def test_equity_residual_renders_a_visible_estimated_marker():
    store = load_master_store(seed_id="ksa_bank")
    tb = [{"account": "EQR", "label": "Combined balancing residual", "current": 2791092.0, "prior": 4170163.0,
           "section": "Equity", "maturity_hint": "Equity",
           "levels": ["Equity", "Equity", "Statutory reserve, retained earnings and treasury shares (net)",
                      "Combined balancing residual", ""]}]
    concept, _ = resolve_row(store, tb[0])
    assert concept is not None and concept.concept_id == "bs_equity_residual"
    maps = [{"account": "EQR", "concept_id": "bs_equity_residual", "client_label": "Combined balancing residual",
             "provenance": "preparer"}]
    m = build_master_fs_export(store, {"client": "d", "master_id": store.master_id, "tb": tb, "mappings": maps,
                                       "extensions": []}, notes_attempted=True)
    assert "bs_equity_residual" in m.judgment_markers and "ESTIMATED" in m.judgment_markers["bs_equity_residual"]
    assert any(str(f[0]) == "caveat:bs_equity_residual" for f in m.findings)   # a FACE-VISIBLE finding
    assert m.not_final                                                  # the statement is flagged not-final
    line = next(l for st in m.statements.values() for l in st if l.concept_id == "bs_equity_residual")
    assert line.judgment_only and "combined balancing residual" in line.label.lower()   # verbatim, marked


# ============================================================ real-file milestone (skip if absent)
def _ingest_real():
    from ai_accountant.tb_ingest.grid import load_grid
    from ai_accountant.tb_ingest.columns import heuristic_column_roles, confirm_column_roles
    from ai_accountant.tb_ingest.parse import detect_header_row, parse_tb, to_engine_inputs
    from ai_accountant.tb_ingest.sign import propose_tb_sign, apply_tb_sign, confirm_tb_sign
    grid = load_grid(str(REAL), sheet="Trial Balance")
    hr = detect_header_row(grid)
    schema = confirm_column_roles(heuristic_column_roles(grid[hr], grid[hr + 1:hr + 6]))
    parsed = parse_tb(grid, schema, header_row=hr)
    _items, tb_rows = to_engine_inputs(parsed)
    sp = propose_tb_sign(tb_rows)
    # SL-1d Fix 1: the heuristic now proposes Expense=flip BY DEFAULT for this positive-stored-expense TB
    # (no manual override needed) — assert it, then apply the defaults verbatim.
    assert next(s.proposed for s in sp.sections if s.section == "Expense") == "flip"
    tb_rows = apply_tb_sign(tb_rows, confirm_tb_sign(sp, {s.section: s.proposed for s in sp.sections},
                                                     approver="r", at="u"))
    return tb_rows


def test_real_tb_full_faces_balance_milestone():
    if not REAL.exists():
        print("[skip] real TB absent"); return
    store = load_master_store(seed_id="ksa_bank")
    tb_rows = _ingest_real()
    maps, unrouted = [], []
    for r in tb_rows:
        c, _ = resolve_row(store, r)
        (maps.append({"account": r["account"], "concept_id": c.concept_id, "client_label": r.get("label", ""),
                      "provenance": "preparer"}) if c else unrouted.append(r))
    m = build_master_fs_export(store, {"client": "draft", "master_id": store.master_id, "tb": tb_rows,
                                       "mappings": maps, "extensions": []}, notes_attempted=True)
    # MILESTONE 1 — the SOFP balances both years (PP&E alias + the equity residual)
    assert not [f for f in m.findings if f[0] == "balance check"], "SOFP does not balance"
    # MILESTONE 2 — only the 3 genuinely-conceptless OCI rows remain unrouted (flagged, never forced)
    assert len(unrouted) == 3, f"{len(unrouted)} unrouted (expected the 3 conceptless OCI movements)"
    assert all("share-based" in (r["levels"][2] + r["levels"][3]).lower() or "transfer to retained" in r["levels"][3].lower()
               for r in unrouted)
    # MILESTONE 3 — the residual marker is visible, the income statement + OCI populate
    assert "bs_equity_residual" in m.judgment_markers and m.not_final
    assert next(l.current for l in m.statements["income_statement"] if l.concept_id == "pl_net_income")
    assert sum(1 for l in m.statements["comprehensive_income"] if l.current and not l.derived) >= 6


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[pass] {name}")
            except AssertionError as exc:
                failures += 1
                print(f"[FAIL] {name}: {str(exc).encode('ascii', 'replace').decode()}")
            except Exception as exc:  # noqa: BLE001
                import traceback
                failures += 1
                print(f"[ERROR] {name}: {exc}")
                traceback.print_exc()
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
