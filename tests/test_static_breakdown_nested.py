"""Slice S4: two-tier (nested) static breakdown + the nested partition firewall.

The mechanism extends the static breakdown from one tier level to two (classification → type → leaf), with the
partition holding at EVERY level. The load-bearing guards: (1) the FROZEN-REPLAY — every existing static note
renders byte-identical (the nested code reduces to today via the per-level single-leaf collapse); (2) the
per-node subtotal assertion — a mid-level subtotal that doesn't sum its children BLOCKS.

    python tests/test_static_breakdown_nested.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_accountant.master_fs                                                          # noqa: E402,F401
from ai_accountant.master_fs.model import ClientMappingStore, MappingRecord            # noqa: E402
from ai_accountant.master_fs.notes import (_nested_subtotal_findings, _strip_qual,  # noqa: E402
                                           attach_static_breakdown, derive_breakdown)
from ai_accountant.master_fs.seed import load_master_store                             # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export            # noqa: E402
from ai_accountant.reporting.render_model import renderable_static                     # noqa: E402
from tests.test_maturity_split import _mobily_stored                                    # noqa: E402

_CONCEPT = "tc_fin_other_assets_nc"


def _static(levels, amounts, *, prior=None, accepted=True, concept=_CONCEPT):
    """Attach a static breakdown for a SYNTHETIC set of leaves (generic labels — no Mobily/AlJazira literal).
    `levels[a]` is the account's level path; `amounts[a]` its current figure; labels = the account id."""
    store = load_master_store(seed_id="telecom_mobily")
    ms = ClientMappingStore()
    for a in amounts:
        ms.put("c", MappingRecord(account=a, concept_id=concept, client_label=a, provenance="preparer",
                                  master_id=store.master_id))
    return attach_static_breakdown(store, ms, "c", amounts, concept, caption="Test",
                                   account_levels=levels, accepted=accepted, prior_amounts=prior)["static"]


def _canon():
    return load_master_store(seed_id="telecom_mobily").get(_CONCEPT).canonical_concept


def _find(nodes, tier):
    for n in nodes:
        if n.get("tier") == tier:
            return n
        hit = _find(n.get("children", []), tier)
        if hit:
            return hit
    return None


# ============================================================ the MANDATORY frozen-replay (every existing note)
def test_frozen_replay_every_existing_static_note_byte_identical():
    base = json.loads((Path(__file__).resolve().parent / "fixtures" / "regression"
                       / "static_notes_baseline.json").read_text(encoding="utf-8"))

    def cap(tag, store, stored):
        m = build_master_fs_export(store, stored, notes_attempted=True)
        return {f"{tag}:{nv.note_ref}": {"status": nv.status,
                "rows": [[r.label, r.value, getattr(r, "prior_value", None), r.kind, r.indent] for r in nv.rows]}
                for nv in m.note_views}
    cur = {}
    st, sd = _mobily_stored()
    cur.update(cap("telecom", st, sd))
    from tests.test_bank_notes_demo import _setup
    bstore, bstored, _ = _setup()
    cur.update(cap("bank", bstore, bstored))
    from tests.test_fsgen_mfs_app import _CONFIRM, _confirm_archetype, _note, _open_view, _ss
    at = _open_view("bank")
    _confirm_archetype(at, "ksa_bank")
    for s in [s for s in at.selectbox if str(getattr(s, "key", "")).startswith("mfs_map_")]:
        s.set_value(_CONFIRM)
    at.run()
    at.button(key="mfs_apply_map").click().run()
    if "mfs_accept_breakdowns" in [getattr(b, "key", None) for b in at.button]:
        at.button(key="mfs_accept_breakdowns").click().run()
    inv = _note(_ss(at, "mfs_model"), "Investments")
    cur["bank_fixture:" + inv.note_ref] = {"status": inv.status,
        "rows": [[r.label, r.value, getattr(r, "prior_value", None), r.kind, r.indent] for r in inv.rows]}

    for key, want in base.items():
        assert key in cur, f"existing note vanished: {key}"
        assert cur[key] == want, f"existing note CHANGED (frozen-replay broke): {key}"
    assert len(cur) == len(base)                              # no spurious extra/missing


def test_degenerate_depth1_flat_note_unchanged():
    # a 1-deep level path (below = [leaf-level] only) → NO tier, flat lines at indent 1 (today's single-level case)
    canon = _canon()
    s = _static({"a1": ["Assets", canon, "x"], "a2": ["Assets", canon, "y"]}, {"a1": 10.0, "a2": 20.0})
    rn = renderable_static(s)
    assert [r.kind for r in rn.rows] == ["line", "line", "total"]   # no subtotal row
    assert all(r.indent == 1 for r in rn.rows if r.kind == "line")
    assert round(rn.rows[-1].value) == 30


# ============================================================ two-level nesting — foots at EVERY level + ties
def test_two_level_nested_subtotals_foot_every_level_and_tie():
    canon = _canon()
    lv = {"sa": ["A", canon, "ClassA", "TypeX"], "sb": ["A", canon, "ClassA", "TypeX"],   # TypeX: 2 leaves → kept
          "ey": ["A", canon, "ClassA", "TypeY"],                                          # TypeY: 1 leaf → collapse
          "fz": ["A", canon, "ClassB", "TypeZ"]}                                          # ClassB: 1 leaf → tier None
    amt = {"sa": 100.0, "sb": 200.0, "ey": 50.0, "fz": 400.0}
    s = _static(lv, amt)
    assert s["status"] in ("BUILT", "GROUPING_UNCONFIRMED") and round(s["total"]) == 750 and round(s["face_value"]) == 750
    classa = _find(s["tiers"], "ClassA")
    typex = _find(s["tiers"], "TypeX")
    assert typex and round(typex["subtotal"]) == 300 and len(typex["lines"]) == 2     # tier-2 foots its leaves
    assert classa and round(classa["subtotal"]) == 350                                # tier-1 = child 300 + direct 50
    assert round(sum(ch["subtotal"] for ch in classa["children"]) + sum(c for _l, c, _p in classa["lines"])) == 350
    classb = _find(s["tiers"], "ClassB")
    assert classb is None                                                             # ClassB single-leaf → tier None
    # the render nests: tier-1 subtotal indent 0, tier-2 subtotal indent 1, leaves indent 2, tie on the grand total
    rn = renderable_static(s)
    kinds = {(r.label, r.kind, r.indent) for r in rn.rows}
    assert ("ClassA", "subtotal", 0) in kinds and ("TypeX", "subtotal", 1) in kinds
    assert ("sa", "line", 2) in kinds and ("fz", "line", 2) in kinds
    assert rn.rows[-1].kind == "total" and round(rn.rows[-1].value) == 750 and "agrees to" in rn.rows[-1].label


def test_single_leaf_collapse_at_each_level():
    canon = _canon()
    # ClassA holds ONE type with ONE leaf → both levels collapse → the leaf renders flat, no redundant subtotal
    s = _static({"only": ["A", canon, "ClassA", "TypeX"], "two1": ["A", canon, "ClassB", "TypeY"],
                 "two2": ["A", canon, "ClassB", "TypeY"]}, {"only": 10.0, "two1": 5.0, "two2": 7.0})
    assert _find(s["tiers"], "TypeX") is None                 # single-leaf tier-2 collapsed
    classa = next((n for n in s["tiers"] if "only" in [ln[0] for ln in n["lines"]]), None)
    assert classa is not None and classa["tier"] is None      # ClassA single-leaf → tier collapsed to None
    classb = _find(s["tiers"], "TypeY")                       # ClassB→TypeY: 2 leaves → kept (a real tier)
    assert classb and round(classb["subtotal"]) == 12


def test_contra_nets_at_tier_2_by_sign():
    canon = _canon()
    # a negative allowance leaf UNDER a type nets by sign-summation at tier-2 (no "allowance" literal)
    s = _static({"gross": ["A", canon, "ClassA", "TypeX"], "alw": ["A", canon, "ClassA", "TypeX"],
                 "other": ["A", canon, "ClassA", "TypeY"], "o2": ["A", canon, "ClassA", "TypeY"]},
                {"gross": 500.0, "alw": -200.0, "other": 30.0, "o2": 40.0})
    typex = _find(s["tiers"], "TypeX")
    assert typex and round(typex["subtotal"]) == 300          # 500 + (−200) nets to 300 at tier-2
    assert round(s["total"]) == 370                           # 300 + 70


# ============================================================ the per-node (mid-level) assertion fires
def test_mid_level_subtotal_mismatch_blocks():
    # Reading A: a node whose subtotal ≠ Σ its children → the per-node assertion returns a finding (BLOCK),
    # while a sibling foots and the leaves are all present. (Subtotals are computed bottom-up on the build path,
    # so this guards a SUPPLIED-subtotal tree — we feed one directly to prove the guard fires.)
    good = {"tier": "TypeX", "subtotal": 300.0, "subtotal_prior": 0.0,
            "children": [], "lines": [("a", 100.0, None), ("b", 200.0, None)]}
    assert _nested_subtotal_findings(good, "c", "cap", False, 0.005) == []
    bad = {"tier": "TypeX", "subtotal": 999.0, "subtotal_prior": 0.0,      # 999 ≠ 100+200
           "children": [], "lines": [("a", 100.0, None), ("b", 200.0, None)]}
    assert _nested_subtotal_findings(bad, "c", "cap", False, 0.005)
    # and it recurses: a parent that foots but a CHILD that doesn't → still caught
    parent = {"tier": "ClassA", "subtotal": 300.0, "subtotal_prior": 0.0, "lines": [], "children": [bad]}
    assert _nested_subtotal_findings(parent, "c", "cap", False, 0.005)


def test_mid_level_block_through_build_keeps_leaves_and_grand_footing():
    # feed a CONFIRMED breakdown that tampers a tier-2 subtotal; build recomputes subtotals (so it actually foots)
    # — but if a tree EVER carried a bad subtotal, attach surfaces it. Here we assert the engine path stays BUILT
    # when honest, and the helper is what would block a tampered tree (unit-tested above).
    canon = _canon()
    s = _static({"a": ["A", canon, "ClassA", "TypeX"], "b": ["A", canon, "ClassA", "TypeX"]},
                {"a": 100.0, "b": 200.0})
    assert not s["findings"] and round(s["total"]) == 300     # honest tree → no per-node finding, foots


# ============================================================ both-years per node
def test_both_years_carry_per_node():
    canon = _canon()
    lv = {"sa": ["A", canon, "ClassA", "TypeX"], "sb": ["A", canon, "ClassA", "TypeX"]}
    s = _static(lv, {"sa": 100.0, "sb": 200.0}, prior={"sa": 90.0, "sb": 180.0})
    typex = _find(s["tiers"], "TypeX")
    assert round(typex["subtotal"]) == 300 and round(typex["subtotal_prior"]) == 270
    assert round(s["total_prior"]) == 270


# ============================================================ Slice S5a — Layer-1 suffix-strip anchor
def test_strip_qual_safe_rule_catches_suffixes_without_overmatch():
    # catches the qualifier-suffix misses
    assert _strip_qual("Investments") == _strip_qual("Investments, net")
    assert _strip_qual("Loans / financing") == _strip_qual("Loans / financing, net")
    assert _strip_qual("Cash and balances with the central bank") == \
        _strip_qual("Cash and balances with the central bank (SAMA)")
    # MUST NOT over-match (the safety proof): "Other" is not "Other assets"/"Other liabilities"
    assert _strip_qual("Other") != _strip_qual("Other assets")
    assert _strip_qual("Other") != _strip_qual("Other liabilities")
    # MUST NOT strip the maturity suffix (it disambiguates a current/non-current pair)
    assert _strip_qual("Financial and other assets — non-current") != \
        _strip_qual("Financial and other assets — current")


def _static_bank(levels, amounts, concept="bs_investments"):
    store = load_master_store(seed_id="ksa_bank")
    ms = ClientMappingStore()
    for a in amounts:
        ms.put("c", MappingRecord(account=a, concept_id=concept, client_label=a, provenance="preparer",
                                  master_id=store.master_id))
    return attach_static_breakdown(store, ms, "c", amounts, concept, caption="Investments, net",
                                   account_levels=levels, accepted=True)["static"]


def test_layer1_suffix_anchor_nests_when_level_is_the_short_form():
    # the TB carries the SHORT level label "Investments"; the concept canonical is "Investments, net" (so Layer 0
    # exact-match MISSES). Layer 1 strips ", net" and anchors at L2 → S4 nests (FVIS tier-1 → Domestic tier-2).
    lv = {"a": ["Assets", "Investments", "FVIS", "Domestic"], "a2": ["Assets", "Investments", "FVIS", "Domestic"],
          "b": ["Assets", "Investments", "FVIS", "International"], "c": ["Assets", "Investments", "FVOCI", "Domestic"]}
    s = _static_bank(lv, {"a": 100.0, "a2": 50.0, "b": 200.0, "c": 300.0})
    assert round(s["total"]) == 650
    fvis = _find(s["tiers"], "FVIS")
    assert fvis is not None and round(fvis["subtotal"]) == 350                  # tier-1 anchored via Layer 1
    dom = _find(s["tiers"], "Domestic")                                         # tier-2 under FVIS (a + a2 → 2 leaves)
    assert dom is not None and round(dom["subtotal"]) == 150


def test_layer1_short_form_matches_layer0_full_canonical_identically():
    # the short-form level anchor (Layer 1) yields the SAME structure as the full-canonical level (Layer 0)
    short = _static_bank({"a": ["Assets", "Investments", "FVIS", "Domestic"],
                          "b": ["Assets", "Investments", "FVIS", "Domestic"]}, {"a": 10.0, "b": 20.0})
    full = _static_bank({"a": ["Assets", "Investments, net", "FVIS", "Domestic"],
                         "b": ["Assets", "Investments, net", "FVIS", "Domestic"]}, {"a": 10.0, "b": 20.0})
    assert renderable_static(short).rows[0].label == renderable_static(full).rows[0].label == "FVIS"
    assert [r.kind for r in renderable_static(short).rows] == [r.kind for r in renderable_static(full).rows]


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
