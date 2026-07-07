"""Slice S2: static breakdown — tiered, source-faithful labels, the AI groups but never renames.

The grouping is a HIERARCHY: deterministic from the TB level hierarchy when present (tiers + source leaf
lines), else an AI-proposed grouping (account sets only; multi-leaf captions human-confirmed), else the
identity floor. Two firewalls hold in BOTH paths: a LEAF line's label is ALWAYS its TB label (a payload
rename is ignored), and the partition must be complete + disjoint (Σ == concept). A BUILT note shows its
total tied to the face value.

    python tests/test_static_breakdown.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.model import ClientMappingStore, MappingRecord                # noqa: E402
from ai_accountant.master_fs.notes import attach_static_breakdown, derive_breakdown        # noqa: E402
from ai_accountant.reporting.render_model import renderable_static                         # noqa: E402

# four leaves under one concept, carrying a TB level hierarchy: L2 concept / L3 tier / L4 leaf
_CONCEPT = "Financial and other assets"
_ROWS = [
    ("a1", "Restricted cash", 250071.0, ["Assets", "NCA", _CONCEPT, "Financial assets", "Restricted cash"]),
    ("a2", "Others", 119670.0, ["Assets", "NCA", _CONCEPT, "Financial assets", "Others"]),
    ("a3", "Capital advances", 300660.0, ["Assets", "NCA", _CONCEPT, "Other assets", "Capital advances"]),
    ("a4", "Others", 138045.0, ["Assets", "NCA", _CONCEPT, "Other assets", "Others"]),
]
_TOTAL = round(sum(a for _c, _l, a, _v in _ROWS), 2)         # 808446


class _Concept:
    canonical_concept = _CONCEPT
    label_aliases = {"x": _CONCEPT}
    statement = "balance_sheet"


class _Store:
    def get(self, cid):
        return _Concept()

    def statement_title(self, key):
        return "Statement of Financial Position"


def _ms(rows):
    ms, tb, levels = ClientMappingStore(), {}, {}
    for a, lbl, amt, lv in rows:
        ms.put("c", MappingRecord(account=a, concept_id="X", client_label=lbl, provenance="ai_confirmed", master_id="m"))
        tb[a] = amt
        levels[a] = lv
    return ms, tb, levels


def _build(rows, **kw):
    ms, tb, levels = _ms(rows)
    return attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, account_levels=levels, **kw)["static"]


def test_levels_path_builds_two_tiers_with_source_labels_and_separate_others():
    res = _build(_ROWS, accepted=True)
    assert res["path"] == "levels" and res["status"] == "BUILT"
    tiers = {t["tier"]: t for t in res["tiers"]}
    assert set(tiers) == {"Financial assets", "Other assets"}              # derived from the L3 level
    assert tiers["Financial assets"]["subtotal"] == 369741.0              # 250071 + 119670
    assert tiers["Other assets"]["subtotal"] == 438705.0                  # 300660 + 138045
    # the TWO "Others" stay SEPARATE (one per tier) — the fused-257,715 bug is fixed
    fin_others = {ln[0]: ln[1] for ln in tiers["Financial assets"]["lines"]}["Others"]
    oth_others = {ln[0]: ln[1] for ln in tiers["Other assets"]["lines"]}["Others"]
    assert fin_others == 119670.0 and oth_others == 138045.0
    assert res["total"] == res["face_value"] == _TOTAL                     # foots to the concept


def test_total_is_shown_tied_to_the_face_on_the_note():
    rn = renderable_static(_build(_ROWS, accepted=True))
    assert rn.rows[-1].kind == "total" and round(rn.rows[-1].raw_sar) == round(_TOTAL)
    assert "agrees to" in rn.rows[-1].label and "Statement of Financial Position" in rn.rows[-1].label
    assert any("consolidates to" in c for c in rn.caveats)                 # stated for the reader


def test_orphaned_leaf_blocks_and_double_count_blocks():
    ms, tb, lv = _ms(_ROWS)
    omit = {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": ["a1", "a2", "a3"]}]}]}   # a4 omitted
    r1 = attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, breakdown=omit, accepted=True)["static"]
    assert r1["status"] == "BLOCKED" and any("OMITS" in f[2] for f in r1["findings"])
    dup = {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": ["a1", "a2", "a3", "a4", "a1"]}]}]}
    r2 = attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, breakdown=dup, accepted=True)["static"]
    assert r2["status"] == "BLOCKED" and any("DOUBLE-COUNTS" in f[2] for f in r2["findings"])


def test_payload_cannot_rename_a_leaf_line_source_label_wins():
    ms, tb, lv = _ms(_ROWS)
    # a single-leaf line carrying a bogus AI caption — the builder MUST use the TB label, not the rename
    bd = {"path": "x", "tiers": [{"tier": None, "lines": [
        {"accounts": ["a1"], "caption": "RENAMED!", "caption_source": "ai"},
        {"accounts": ["a2"]}, {"accounts": ["a3"]}, {"accounts": ["a4"]}]}]}
    res = attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, breakdown=bd, accepted=True)["static"]
    labels = [ln[0] for t in res["tiers"] for ln in t["lines"]]
    assert "RENAMED!" not in labels and "Restricted cash" in labels        # source label wins, rename rejected


def test_ai_caption_for_a_multi_leaf_group_stays_unconfirmed_until_human_confirms():
    ms, tb, lv = _ms(_ROWS)
    ai = {"path": "ai", "tiers": [{"tier": None, "lines": [
        {"accounts": ["a1", "a2"], "caption": "Sundries", "caption_source": "ai"},
        {"accounts": ["a3", "a4"], "caption": "Advances", "caption_source": "ai"}]}]}
    r1 = attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, breakdown=ai, accepted=True)["static"]
    assert r1["status"] == "GROUPING_UNCONFIRMED" and r1["ai_caption_unconfirmed"]   # accepted, but AI caption unreviewed
    for t in ai["tiers"]:
        for ln in t["lines"]:
            ln["caption_source"] = "confirmed"                             # the human confirms the captions
    r2 = attach_static_breakdown(_Store(), ms, "c", tb, "X", caption=_CONCEPT, breakdown=ai, accepted=True)["static"]
    assert r2["status"] == "BUILT"


def test_path_is_recorded_levels_vs_ai_vs_identity():
    ms, tb, lv = _ms(_ROWS)
    tiers_lv, path_lv = derive_breakdown(_Store(), "X", tb, {a: l for a, l, _amt, _v in _ROWS}, lv, client=None)
    assert path_lv == "levels"                                             # TB carries the hierarchy

    class _Stub:                                                           # AI fallback when there are no levels
        def complete_json(self, p, system=None, **k):
            return {"components": [{"accounts": ["a1", "a2"], "caption": "Sundries"}, {"accounts": ["a3", "a4"]}]}
    flat_labels = {a: l for a, l, _amt, _v in _ROWS}
    _t, path_ai = derive_breakdown(_Store(), "X", tb, flat_labels, {}, client=_Stub())   # no levels → AI
    assert path_ai == "ai"
    _t2, path_id = derive_breakdown(_Store(), "X", tb, flat_labels, {}, client=None)      # no levels, no AI → identity
    assert path_id == "identity"


def test_unaccepted_levels_grouping_is_not_final():
    assert _build(_ROWS, accepted=False)["status"] == "GROUPING_UNCONFIRMED"


# ----------------------------------------------------------------------------- Slice S3a: plain + contra
class _FlexConcept:
    def __init__(self, canon):
        self.canonical_concept, self.label_aliases, self.statement = canon, {}, "balance_sheet"


class _FlexStore:
    def __init__(self, canon):
        self._c = _FlexConcept(canon)

    def get(self, cid):
        return self._c

    def statement_title(self, key):
        return "Statement of Financial Position"


def _build_flex(canon, rows, **kw):
    ms, tb, lv = ClientMappingStore(), {}, {}
    for a, lbl, amt, levels in rows:
        ms.put("c", MappingRecord(account=a, concept_id="X", client_label=lbl, provenance="ai_confirmed", master_id="m"))
        tb[a], lv[a] = amt, levels
    return attach_static_breakdown(_FlexStore(canon), ms, "c", tb, "X", caption=canon,
                                   account_levels=lv, accepted=True, **kw)["static"]


def _is_tiered(res):
    return any(t.get("tier") for t in res["tiers"])            # mirrors renderable_static's multi_tier (subtotals)


def test_contra_nets_by_summation_to_the_face_no_special_code():
    # gross + a NEGATIVE allowance leaf nets to the face by summation — no contra branch, no "Less:" match
    rows = [("g", "Accounts receivable", 100.0, ["A", "CA", "Accounts receivable", "Accounts receivable", "Accounts receivable"]),
            ("a", "Less: allowance for impairment", -30.0, ["A", "CA", "Accounts receivable", "Less: allowance", "Less: allowance"])]
    res = _build_flex("Accounts receivable", rows)
    assert res["status"] == "BUILT" and res["total"] == 70.0 == res["face_value"]   # nets to the net face
    lines = [(ln[0], ln[1]) for t in res["tiers"] for ln in t["lines"]]
    assert ("Accounts receivable", 100.0) in lines and ("Less: allowance for impairment", -30.0) in lines


def test_single_leaf_tiers_collapse_to_flat_lines():
    # the concept name repeating at L2/L3 + a differently-named allowance → two single-leaf tiers → FLAT
    rows = [("g", "Accounts receivable", 100.0, ["A", "CA", "Accounts receivable", "Accounts receivable", "Accounts receivable"]),
            ("a", "Less: allowance", -30.0, ["A", "CA", "Accounts receivable", "Less: allowance", "Less: allowance"])]
    res = _build_flex("Accounts receivable", rows)
    assert not _is_tiered(res)                                  # rendered flat, no spurious single-line tiers


def test_non_footing_contra_blocks():
    rows = [("g", "Gross", 100.0, ["A", "CA", "X", "Gross", "Gross"])]
    bad = {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": ["g"]}]}]}   # leaves out the allowance below
    ms, tb, lv = ClientMappingStore(), {"g": 100.0, "a": -30.0}, {}
    for code in ("g", "a"):
        ms.put("c", MappingRecord(account=code, concept_id="X", client_label=code, provenance="ai_confirmed", master_id="m"))
    res = attach_static_breakdown(_FlexStore("X"), ms, "c", tb, "X", caption="X", breakdown=bad, accepted=True)["static"]
    assert res["status"] == "BLOCKED" and any("OMITS" in f[2] for f in res["findings"])


def test_anti_hardcoding_contra_label_independent_and_sign_only():
    # (1) a DIFFERENTLY-named contra ("Accumulated depreciation"), non-Mobily concept names → nets + foots
    r1 = _build_flex("Equipment", [
        ("c", "Machinery", 1000.0, ["A", "NCA", "Equipment", "Machinery", "Machinery"]),
        ("d", "Accumulated depreciation", -400.0, ["A", "NCA", "Equipment", "Acc dep", "Accumulated depreciation"])])
    assert r1["status"] == "BUILT" and r1["total"] == 600.0
    # (2) a SIGN-ONLY contra — a negative leaf with NO contra word at all → still nets by sign
    r2 = _build_flex("Sundry assets", [
        ("x", "Opening balance", 1000.0, ["A", "CA", "Sundry assets", "Opening", "Opening balance"]),
        ("y", "Adjustment", -250.0, ["A", "CA", "Sundry assets", "Adj", "Adjustment"])])
    assert r2["status"] == "BUILT" and r2["total"] == 750.0   # nothing keyed on a label; summation did it


def test_non_mobily_two_layer_sign_only_contra_nbv_by_class_foots():
    # a TWO-LAYER note (Thread 1): each class tier = cost (+) and a SIGN-ONLY negative leaf (no contra word)
    # → NBV-by-class subtotal; the grand total foots. Different concept/class names, no Mobily literal.
    rows = [("m_c", "Machinery", 1000.0, ["A", "NCA", "Plant", "Machinery", "Machinery"]),
            ("m_d", "wear and tear", -400.0, ["A", "NCA", "Plant", "Machinery", "wear and tear"]),
            ("v_c", "Vehicles", 500.0, ["A", "NCA", "Plant", "Vehicles", "Vehicles"]),
            ("v_d", "wear and tear", -150.0, ["A", "NCA", "Plant", "Vehicles", "wear and tear"])]
    res = _build_flex("Plant", rows)
    assert res["status"] == "BUILT" and res["total"] == 950.0          # (1000−400) + (500−150)
    tiers = {t["tier"]: t["subtotal"] for t in res["tiers"] if t.get("tier")}
    assert tiers == {"Machinery": 600.0, "Vehicles": 350.0}            # NBV by class, the class-tier subtotals


# ----------------------------------------------------------------------------- Slice S3b Thread 2: comparatives
def _ms_pc(rows):
    ms = ClientMappingStore()
    for a, lbl in rows:
        ms.put("c", MappingRecord(account=a, concept_id="X", client_label=lbl, provenance="ai_confirmed", master_id="m"))
    return ms


def test_prior_column_both_years_foot_independently():
    ms = _ms_pc([("g", "Gross"), ("al", "Less: allowance")])
    cur, pri = {"g": 100.0, "al": -30.0}, {"g": 80.0, "al": -20.0}
    res = attach_static_breakdown(_FlexStore("X"), ms, "c", cur, "X", caption="X",
                                  prior_amounts=pri, accepted=True)["static"]
    assert res["status"] == "BUILT" and res["has_prior"]
    assert res["total"] == 70.0 == res["face_value"]                   # current foots
    assert res["total_prior"] == 60.0 == res["face_value_prior"]       # prior foots INDEPENDENTLY


def test_prior_firewall_blocks_when_a_prior_only_leaf_is_dropped():
    # a leaf with ZERO current but NONZERO prior — dropping it leaves the CURRENT sum footing (it's 0) but
    # robs the PRIOR column → the partition guard BLOCKS (the prior column is not a passenger)
    ms = _ms_pc([("g", "Gross"), ("al", "Less: allowance"), ("z", "Prior-only item")])
    cur, pri = {"g": 100.0, "al": -30.0, "z": 0.0}, {"g": 80.0, "al": -20.0, "z": 50.0}
    drop_z = {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": ["g"]}, {"accounts": ["al"]}]}]}
    res = attach_static_breakdown(_FlexStore("X"), ms, "c", cur, "X", caption="X",
                                  prior_amounts=pri, breakdown=drop_z, accepted=True)["static"]
    assert res["status"] == "BLOCKED"                                  # current would foot at 70, but prior is robbed
    # the complete partition foots BOTH years (current 70, prior 110)
    ok = attach_static_breakdown(_FlexStore("X"), ms, "c", cur, "X", caption="X",
                                 prior_amounts=pri, accepted=True)["static"]
    assert ok["status"] == "BUILT" and ok["total"] == 70.0 and ok["total_prior"] == 110.0


def test_no_prior_supplied_no_phantom_column():
    ms = _ms_pc([("g", "Gross"), ("al", "Less: allowance")])
    res = attach_static_breakdown(_FlexStore("X"), ms, "c", {"g": 100.0, "al": -30.0}, "X",
                                  caption="X", accepted=True)["static"]    # no prior_amounts
    assert res["status"] == "BUILT" and res["has_prior"] is False and res["total_prior"] is None


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
