"""Slice B2a: the current/non-current split is HONEST — flag-don't-lump.

A seed-declared maturity pair the TB can't actually split (only one side populated) surfaces as a finding +
`split_undetermined`, never a clean-footing wrong split. The pairing is deterministic (alias/base match)
with an AI-fallback for ambiguous cases (labels-only, human-confirmed) and a flag-floor. The blank-hint
silent default is killed. Detection (one-sided?) is ARITHMETIC; the AI only proposes WHICH concepts pair.

    python tests/test_maturity_split.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.mapping import (apply_mapping_decisions, propose_maturity_pairing)   # noqa: E402
from ai_accountant.master_fs.model import (ClientMappingStore, MasterConcept, MasterStructureStore,  # noqa: E402
                                           ProvenanceStore)
from ai_accountant.master_fs.orchestrator import _stored_from_mapping                  # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                             # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export            # noqa: E402
from ai_accountant.tb_ingest import (apply_tb_sign, confirm_column_roles, confirm_tb_sign,  # noqa: E402
                                     detect_header_row, load_grid, parse_tb, propose_column_roles,
                                     propose_tb_sign, to_engine_inputs)
from ai_accountant.tb_ingest.resolve import build_upload_proposals, resolve_concept    # noqa: E402

TB = Path(__file__).resolve().parent / "fixtures" / "tb_upload" / "tb_test.xlsx"


def _mobily_stored():
    grid = load_grid(str(TB))
    hdr = detect_header_row(grid)
    schema = confirm_column_roles(propose_column_roles(grid[hdr], grid[hdr + 1:hdr + 6], client=None))
    _items, tb_rows = to_engine_inputs(parse_tb(grid, schema, header_row=hdr))
    tb_rows = apply_tb_sign(tb_rows, confirm_tb_sign(propose_tb_sign(tb_rows), approver="t", at="t"))
    store = load_master_store(seed_id="telecom_mobily")
    ms, au = ClientMappingStore(), ProvenanceStore()
    props = build_upload_proposals(tb_rows, store, client=None)
    apply_mapping_decisions(props, store, client_id="tb", decisions={p.code: "confirm" for p in props},
                            mapping_store=ms, audit=au, approver="t", at="t")
    return store, _stored_from_mapping(ms, "tb", store.master_id, tb_rows)


def _su(model):
    return {l.concept_id for st in model.statements.values() for l in st if l.split_undetermined}


# ----------------------------------------------------------------------------- the helper itself
def test_maturity_pairs_derived_clean_for_telecom_none_for_bank():
    clean, ambiguous = load_master_store(seed_id="telecom_mobily").maturity_pairs()
    assert len(clean) == 7 and ambiguous == []                  # 3 asset + 4 liability pairs, all clean
    assert load_master_store(seed_id="ksa_bank").maturity_pairs() == ([], [])   # liquidity-presented → no-op


def test_ambiguous_pairing_is_surfaced_not_silently_paired():
    store = MasterStructureStore(meta={"current_non_current_split": True})
    store.add(MasterConcept("a_nc", "balance_sheet", "NCA", None, "Widgets — non-current", {}, "p", 10))
    store.add(MasterConcept("a_c", "balance_sheet", "CA", None, "Widgets — current", {}, "p", 20))
    store.add(MasterConcept("b_nc", "balance_sheet", "NCA", None, "Gadgets — non-current", {}, "p", 30))  # orphan
    clean, ambiguous = store.maturity_pairs()
    assert ("a_nc", "a_c") in clean                             # clean pair found
    assert any(amb["base"] == "gadgets" for amb in ambiguous)   # orphan half surfaced, not silently paired


# ----------------------------------------------------------------------------- the Mobily acceptance test
def test_mobily_three_asset_pairs_flag_split_undetermined_liabilities_unflagged():
    store, stored = _mobily_stored()
    m = build_master_fs_export(store, stored, notes_attempted=True)
    su = _su(m)
    assert su == {"tc_contract_costs_nc", "tc_contract_assets_nc", "tc_fin_other_assets_nc"}   # the 3 lumped
    assert len([f for f in m.findings if str(f[0]).startswith("maturity:")]) == 3
    # the four genuine two-sided liability pairs are NOT flagged
    for cid in ("tc_borrowings_nc", "tc_lease_liab_nc", "tc_contract_liab_nc", "tc_fin_other_liab_nc"):
        assert cid not in su
    # money/totals untouched (only the split presentation + the finding changed)
    ta = next(l.current for st in m.statements.values() for l in st if l.concept_id == "tc_total_assets")
    assert round(ta) == 38515028


def test_split_undetermined_total_is_unchanged_and_no_new_balance_finding():
    from ai_accountant.master_fs.close import apply_retained_close, detect_close_state
    store, stored = _mobily_stored()
    cp = detect_close_state(store, build_master_fs_export(store, stored))
    stored = apply_retained_close(stored, cp, approver="t", at="t")
    m = build_master_fs_export(store, stored, notes_attempted=True)
    assert not [f for f in m.findings if f[0] == "balance check"]   # SOFP still balances; guard added no imbalance
    assert _su(m) == {"tc_contract_costs_nc", "tc_contract_assets_nc", "tc_fin_other_assets_nc"}
    assert m.not_final is True                                       # the undetermined split keeps it not-final


# ----------------------------------------------------------------------------- the resolver default kill
def test_blank_maturity_hint_returns_none_never_silently_picks_a_side():
    store = load_master_store(seed_id="telecom_mobily")
    lv = ["Assets", "", "Contract costs"]
    assert resolve_concept(store, "Contract costs", "", levels=lv) is None          # blank → undetermined, not _c
    assert resolve_concept(store, "Contract costs", "Non-Current Assets",
                           levels=["Assets", "Non-Current Assets", "Contract costs"]).concept_id == "tc_contract_costs_nc"
    assert resolve_concept(store, "Contract costs", "Current Assets",
                           levels=["Assets", "Current Assets", "Contract costs"]).concept_id == "tc_contract_costs_c"


# ----------------------------------------------------------------------------- the AI-fallback pairing
def test_ai_fallback_pairing_proposes_validates_and_flag_floor():
    cands = [("z_nc", "Sprockets — non-current", "nc"), ("z_c", "Sprockets — current", "c")]

    class _Stub:
        def __init__(self, payload):
            self.payload = payload

        def complete_json(self, p, system=None, **k):
            return self.payload
    # proposes a valid one-nc/one-c pairing
    paired = propose_maturity_pairing(cands, client=_Stub({"pairings": [{"non_current": "z_nc", "current": "z_c"}]}))
    assert paired == [("z_nc", "z_c")]
    # FLAG-FLOOR: an unconfident model (no pairings) → nothing paired (the build guard then flags them)
    assert propose_maturity_pairing(cands, client=_Stub({"pairings": []})) == []
    # a bogus pairing (both non-current) is rejected — never a forced mispair
    assert propose_maturity_pairing(cands, client=_Stub({"pairings": [{"non_current": "z_nc", "current": "z_nc"}]})) == []
    # no client → no AI (deterministic-only path)
    assert propose_maturity_pairing(cands, client=None) == []


def test_unconfirmed_ambiguous_pair_is_flagged_confirmed_pair_is_honoured():
    # inject an orphan non-current half into the telecom store → maturity_pairs() reports it ambiguous
    store, stored = _mobily_stored()
    store.add(MasterConcept("tc_orphan_nc", "balance_sheet", "NON_CURRENT_ASSETS", None,
                            "Orphan item — non-current", {}, "mobily", 95))
    m = build_master_fs_export(store, stored, notes_attempted=True)
    assert any(str(f[0]).startswith("maturity_pair:") for f in m.findings)          # unconfirmed → flagged
    # a human-confirmed pairing (stored) is honoured — the ambiguous finding for it disappears
    stored2 = {**stored, "maturity_pairs_confirmed": [["tc_orphan_nc", "tc_fin_other_assets_c"]]}
    m2 = build_master_fs_export(store, stored2, notes_attempted=True)
    assert not any("orphan" in str(f[1]).lower() for f in m2.findings if str(f[0]).startswith("maturity_pair:"))


def test_b2a_s3a_coexistence_on_contract_costs_and_assets():
    """The same face line carries BOTH a B2a 'split undetermined' marker (the TB couldn't split nc/c) AND a
    BUILT S3a static breakdown of its composition — orthogonal (nc/c split ACROSS concepts vs composition
    WITHIN one), neither suppressing, double-counting, or corrupting the other."""
    from ai_accountant.master_fs.notes import derive_breakdown
    store, stored = _mobily_stored()
    cur = {t["account"]: t["current"] for t in stored["tb"]}
    lvl = {t["account"]: t.get("levels", []) for t in stored["tb"]}
    bd = {}
    for c in ("tc_contract_costs_nc", "tc_contract_assets_nc"):
        mp = {m["account"]: cur.get(m["account"], 0.0) for m in stored["mappings"]
              if m["concept_id"] == c and m["account"] in cur}
        lb = {m["account"]: m.get("client_label", "") for m in stored["mappings"] if m["concept_id"] == c}
        tiers, path = derive_breakdown(store, c, mp, lb, lvl, client=None)
        bd[c] = {"tiers": tiers, "path": path}
    m = build_master_fs_export(store, {**stored, "breakdowns": bd}, notes_attempted=True)
    su = _su(m)
    nv = {v.note_ref: v for v in m.note_views}

    def face(c):
        return next(l.current for st in m.statements.values() for l in st if l.concept_id == c)

    for cid, cap in (("tc_contract_costs_nc", "Contract costs"),
                     ("tc_contract_assets_nc", "Contract assets (net of allowance)")):
        assert cid in su                                       # B2a face marker present
        assert nv[cap].status == "BUILT"                       # AND a BUILT breakdown
        assert round(nv[cap].rows[-1].raw_sar) == round(face(cid))   # footing to the (lumped) concept value


def test_mobily_static_notes_show_prior_column_footing_to_prior_face():
    """Slice S3b Thread 2: the Mobily TB carries 2024 + 2023, so each static note shows current + prior, and
    the PRIOR breakdown foots to the PRIOR-year face value (independently of the current column)."""
    from ai_accountant.master_fs.notes import derive_breakdown
    store, stored = _mobily_stored()
    cur = {t["account"]: t["current"] for t in stored["tb"]}
    lvl = {t["account"]: t.get("levels", []) for t in stored["tb"]}
    bd = {}
    for d in store.meta["notes"]:
        if d.get("mechanism") == "static_breakdown":
            c = d["concept"]
            mp = {m["account"]: cur.get(m["account"], 0.0) for m in stored["mappings"]
                  if m["concept_id"] == c and m["account"] in cur}
            if len(mp) > 1:
                lb = {m["account"]: m.get("client_label", "") for m in stored["mappings"] if m["concept_id"] == c}
                t, p = derive_breakdown(store, c, mp, lb, lvl, client=None)
                bd[c] = {"tiers": t, "path": p}
    m = build_master_fs_export(store, {**stored, "breakdowns": bd}, notes_attempted=True)
    nv = {v.note_ref: v for v in m.note_views}

    def prior_face(c):
        return next((l.prior for st in m.statements.values() for l in st if l.concept_id == c), None)

    for cap, c, exp in (("Property and equipment", "tc_ppe", 19011971),
                        ("Accounts receivable (net of allowance)", "tc_accounts_receivable", 3390534)):
        tot = nv[cap].rows[-1]
        assert tot.prior_value is not None and round(tot.prior_value) == exp == round(prior_face(c))


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
