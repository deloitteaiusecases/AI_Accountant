"""Slice S3c: the AI SURVEY proposes the note agenda; the engine PROVES every number.

The safety case, tested two ways per the settled split:
  * DETERMINISTIC (no model): the no-magnitude payload guard fires EVERY run; the firewall is exercised with
    HAND-WRITTEN agendas (a footing one → BUILT, a non-footing one → BLOCKED, a hallucinated one → not
    generated); the seed-floor↔agenda reconciliation (None → floor, agenda supersedes, exactly-one-writes).
  * LIVE (real model, skipped without a key): propose_note_agenda actually proposes; the wrapper sanitises
    its output to the payload's concepts.
The AI authors neither a number nor a status — it only names what to ATTEMPT.

    python tests/test_note_agenda.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.mapping import agenda_payload, propose_note_agenda                 # noqa: E402
from ai_accountant.master_fs.model import ClientMappingStore, MappingRecord                     # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                                      # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export                     # noqa: E402
from tests.test_maturity_split import _mobily_stored                                            # noqa: E402


def _ms(stored, store):
    ms = ClientMappingStore()
    for m in stored["mappings"]:
        ms.put("c", MappingRecord(account=m["account"], concept_id=m.get("concept_id"),
                                  client_label=m.get("client_label", ""), provenance="preparer",
                                  master_id=store.master_id))
    return ms


def _views(model):
    return {v.note_ref: v.status for v in model.note_views}


# ----------------------------------------------------------------------------- the ENFORCED no-magnitude guard
def test_agenda_payload_carries_no_magnitude_enforced_every_run():
    store, stored = _mobily_stored()
    cur = {t["account"]: t["current"] for t in stored["tb"]}
    lvl = {t["account"]: t.get("levels", []) for t in stored["tb"]}
    payload = agenda_payload(store, _ms(stored, store), "c", cur, lvl)
    assert payload                                              # there ARE concepts to survey

    def walk(o, key=None):                                     # STRUCTURAL assertion — fires on every run
        if isinstance(o, bool):
            return
        if isinstance(o, float):
            raise AssertionError(f"MAGNITUDE (float) reached the payload at {key!r}")
        if isinstance(o, int) and key != "leaf_count":
            raise AssertionError(f"numeric value at {key!r} — only the integer 'leaf_count' may be numeric")
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
    walk(payload)                                              # raises if ANY monetary magnitude appears
    for c in payload:                                          # the sign is a FLAG, never a value
        for leaf in c["leaves"]:
            assert leaf["sign"] in ("+", "-") and isinstance(leaf["label"], str)
        assert isinstance(c["leaf_count"], int)


def test_payload_sign_flags_reflect_structure_not_value():
    store, stored = _mobily_stored()
    cur = {t["account"]: t["current"] for t in stored["tb"]}
    payload = agenda_payload(store, _ms(stored, store), "c", cur, {})
    ppe = next(c for c in payload if c["concept_id"] == "tc_ppe")
    assert {leaf["sign"] for leaf in ppe["leaves"]} == {"+", "-"}   # cost (+) and accumulated depreciation (−)
    # no leaf carries a number — only a label + a sign
    assert all(set(leaf) == {"label", "sign"} for leaf in ppe["leaves"])


# ----------------------------------------------------------------------------- the DETERMINISTIC firewall (no model)
def test_firewall_agenda_concept_that_doesnt_foot_is_blocked_never_built():
    store, stored = _mobily_stored()
    # a hand-written agenda + a deliberately-incomplete breakdown for tc_cash (omits leaves) → must BLOCK
    cash_accts = [m["account"] for m in stored["mappings"] if m["concept_id"] == "tc_cash"]
    bad = {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": [cash_accts[0]]}]}]}   # drops the rest
    m = build_master_fs_export(store, {**stored, "agenda": {"buildable": ["tc_cash"]},
                                       "breakdowns": {"tc_cash": bad}}, notes_attempted=True)
    assert _views(m).get("Cash and cash equivalents") == "BLOCKED"   # proposed but does not reconcile


def test_firewall_hallucinated_concept_renders_not_generated_never_built():
    store, stored = _mobily_stored()
    m = build_master_fs_export(store, {**stored, "agenda": {"buildable": ["tc_does_not_exist"]}},
                               notes_attempted=True)
    assert not any("does_not_exist" in v.note_ref for v in m.note_views)   # nothing to sum → not in views


def test_firewall_valid_agenda_concept_builts_with_the_engines_own_number():
    store, stored = _mobily_stored()
    m = build_master_fs_export(store, {**stored, "agenda": {"buildable": ["tc_cash"]},
                                       "breakdowns": {"tc_cash": _full_cash(store, stored)}}, notes_attempted=True)
    cash = next(v for v in m.note_views if v.note_ref == "Cash and cash equivalents")
    assert cash.status == "BUILT"
    assert round(cash.rows[-1].raw_sar) == 1399542            # the engine's OWN sum from the TB, not the agenda's


def _full_cash(store, stored):
    accts = [m["account"] for m in stored["mappings"] if m["concept_id"] == "tc_cash"]
    return {"path": "x", "tiers": [{"tier": None, "lines": [{"accounts": [a]} for a in accts]}]}


# ----------------------------------------------------------------------------- seed-floor ↔ agenda reconciliation
def test_agenda_none_is_the_seed_floor_and_agenda_supersedes():
    store, stored = _mobily_stored()
    floor = {r for r, s in _views(build_master_fs_export(store, stored, notes_attempted=True)).items()
             if s in ("BUILT", "GROUPING_UNCONFIRMED")}
    assert len(floor) >= 6                                     # the seed-declared static notes build (the floor)
    only_cash = build_master_fs_export(store, {**stored, "agenda": {"buildable": ["tc_cash"]}}, notes_attempted=True)
    built = [r for r, s in _views(only_cash).items() if s in ("BUILT", "GROUPING_UNCONFIRMED")]
    assert built == ["Cash and cash equivalents"]             # the agenda SUPERSEDES the floor (only cash attempted)


def test_dual_mechanism_gl_pick_survives_the_agenda():
    # the bank PP&E has a GL → even if an agenda lists bs_ppe, the roll_forward movement still wins (one writes)
    from tests.test_bank_notes_demo import _setup
    bstore, bstored, payloads = _setup()
    from ai_accountant.master_fs import generate_master_fs
    res = generate_master_fs({**bstored, "agenda": {"buildable": ["bs_ppe"]}}, seed_id="ksa_bank",
                             client="x", strategy="replay", bank="b", gl=payloads)
    ppe = next(v for v in res.model.note_views if v.note_ref.startswith("Property"))
    assert ppe.status == "BUILT" and any(r.label.lower() == "opening" for r in ppe.rows)   # the MOVEMENT, not static


# ----------------------------------------------------------------------------- the proposer wrapper + live
def test_proposer_sanitises_output_to_payload_ids():
    # a one-off fake (NOT _DemoLLM; tests the WRAPPER's id-validation, not the model): a hallucinated id is dropped
    class _Fake:
        def complete_json(self, prompt, system=None, **k):
            return {"buildable": ["tc_cash", "tc_made_up"], "not_buildable": [], "semantic_material": {"tc_cash": True}}
    payload = [{"concept_id": "tc_cash", "label": "Cash", "leaf_count": 2,
                "leaves": [{"label": "x", "sign": "+"}], "levels": []}]
    out = propose_note_agenda(payload, client=_Fake())
    assert out["buildable"] == ["tc_cash"] and "tc_made_up" not in out["buildable"]   # hallucination sanitised


def test_propose_note_agenda_live_if_key_present():
    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] no OPENAI_API_KEY — the live survey proposer is not exercised")
        return
    store, stored = _mobily_stored()
    cur = {t["account"]: t["current"] for t in stored["tb"]}
    lvl = {t["account"]: t.get("levels", []) for t in stored["tb"]}
    out = propose_note_agenda(agenda_payload(store, _ms(stored, store), "c", cur, lvl))   # live model
    ids = {c["concept_id"] for c in agenda_payload(store, _ms(stored, store), "c", cur, lvl)}
    assert set(out["buildable"]) <= ids                       # only real concepts; the engine still foot-checks


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
