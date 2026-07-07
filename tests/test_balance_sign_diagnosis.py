"""Slice S6a: deterministic balance-failure sign-diagnosis (no AI, no key).

When the SOFP does not tie, a deterministic detector finds a mis-signed CONTRA — a leaf subtracted by its
roll-up formula whose sign-FLIP makes the balance re-derive to zero (the double-negation signature) — proposes
the single clean candidate (defers on >1, stays flagged on 0), a human confirms a PER-TB correction, and the
SAME balance-check RE-PROVES it. A wrong correction never clears the firewall. No concept literal.

    python tests/test_balance_sign_diagnosis.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_accountant.master_fs                                                          # noqa: E402,F401
from ai_accountant.master_fs.derive import balance_difference, derive_statement, diagnose_balance  # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                             # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export            # noqa: E402

_BAL = lambda m: any(f[0] == "balance check" for f in m.findings)   # noqa: E731
_LINE = lambda m, cid: next((l for st in m.statements.values() for l in st if l.concept_id == cid), None)  # noqa: E731


def _bank_stored(treasury):
    store = load_master_store(seed_id="ksa_bank")

    def mp(a, cid, lbl):
        return {"account": a, "concept_id": cid, "client_label": lbl, "provenance": "preparer",
                "confidence": "", "flagged_reason": ""}
    # balances IFF treasury is additive; the seed formula SUBTRACTS it → off by 2×treasury when stored negative
    stored = {"client": "x", "master_id": store.master_id, "extensions": [],
              "tb": [{"account": "a1", "label": "Cash", "current": 900.0, "prior": 900.0},
                     {"account": "a2", "label": "Share capital", "current": 1000.0, "prior": 1000.0},
                     {"account": "a3", "label": "Treasury shares", "current": treasury, "prior": treasury}],
              "mappings": [mp("a1", "bs_cash", "Cash"), mp("a2", "bs_share_cap", "Share capital"),
                           mp("a3", "bs_treasury", "Treasury shares")]}
    return store, stored


# ============================================================ Issue 2 — fixed end-to-end (no AI, no key)
def test_treasury_double_negation_diagnosed_confirmed_and_reproven():
    store, stored = _bank_stored(-100.0)
    m0 = build_master_fs_export(store, stored)
    assert _BAL(m0)                                          # the SOFP does not tie (off by 2×100)
    assert len(m0.sign_candidates) == 1                      # exactly ONE clean candidate (never a guess)
    cand = m0.sign_candidates[0]
    assert cand["concept_id"] == "bs_treasury" and cand["formula_sign"] == "-" and cand["corrected_sign"] == "+"
    assert cand["flip_cancels"] and abs(cand["imbalance_multiple"]) == 2
    assert all(not isinstance(v, float) for v in cand.values())   # payload carries NO SAR magnitude (S6b-ready)

    corr = {cand["concept_id"]: cand["corrected_sign"]}
    m1 = build_master_fs_export(store, {**stored, "sign_corrections": corr, "sign_corrections_confirmed": True})
    assert not _BAL(m1) and not m1.not_final                 # RE-PROVEN: the balance-check clears
    assert _LINE(m1, "bs_treasury").current == -100.0        # the LINE still shows the stored sign (presentation)
    assert _LINE(m1, "bs_total_equity").current == 900.0     # the TOTAL is corrected (1000 + (−100))


def test_wrong_correction_stays_flagged_the_firewall_reproves():
    store, stored = _bank_stored(-100.0)
    # a WRONG correction (flip share capital) — the balance-check RE-RUNS and does NOT clear
    m = build_master_fs_export(store, {**stored, "sign_corrections": {"bs_share_cap": "-"},
                                       "sign_corrections_confirmed": True})
    assert _BAL(m)                                           # still off → still flagged (the proposal is never trusted)


def test_unconfirmed_correction_is_not_applied():
    store, stored = _bank_stored(-100.0)
    # present but NOT confirmed → no override applied → stays flagged (nothing auto-applies)
    m = build_master_fs_export(store, {**stored, "sign_corrections": {"bs_treasury": "+"}})
    assert _BAL(m) and _LINE(m, "bs_total_equity").current == 1100.0


def test_clean_balance_runs_no_diagnosis_no_candidates():
    store, stored = _bank_stored(-100.0)
    # the correctly-signed run (apply the confirmed correction) balances → diagnose never runs
    m = build_master_fs_export(store, {**stored, "sign_corrections": {"bs_treasury": "+"},
                                       "sign_corrections_confirmed": True})
    assert not _BAL(m) and m.sign_candidates == []


# ============================================================ generality + ambiguity (constructed stores, no literal)
def _fake_store(leaf_signs):
    """A minimal store: assets = al; L+E = el ± each contra. `leaf_signs` = [(cid, formula_sign, value)] contras."""
    def leaf(cid, order):
        return types.SimpleNamespace(concept_id=cid, canonical_concept=cid, is_computed=False, components=[],
                                     kind="leaf", statement="bs", order=order)
    concepts = {"al": leaf("al", 1), "el": leaf("el", 2)}
    tle_comps = [("+", "el")]
    for i, (cid, sgn, _v) in enumerate(leaf_signs):
        concepts[cid] = leaf(cid, 3 + i)
        tle_comps.append((sgn, cid))
    concepts["ta"] = types.SimpleNamespace(concept_id="ta", is_computed=True, components=[("+", "al")],
                                           kind="total", statement="bs", order=20)
    concepts["tle"] = types.SimpleNamespace(concept_id="tle", is_computed=True, components=tle_comps,
                                            kind="total", statement="bs", order=21)
    return types.SimpleNamespace(concepts=concepts, get=lambda cid: concepts.get(cid),
                                 statement=lambda s: [c for c in concepts.values() if c.statement == s],
                                 balance_check=lambda: {"statement": "bs", "assets_total": "ta",
                                                        "liab_equity_total": "tle"})


def test_generality_a_non_treasury_contra_is_detected_no_literal():
    # a mis-signed contra under a NON-treasury concept id — the detector is structural, names no literal
    store = _fake_store([("xx_provision", "-", -100.0)])
    leaf_amounts = {"al": 100.0, "el": 200.0, "xx_provision": -100.0}     # tle = 200 −(−100) = 300 vs ta 100 → −200
    diff = balance_difference(store, derive_statement(store, "bs", leaf_amounts)[0])
    cands = diagnose_balance(store, "bs", leaf_amounts, diff)
    assert len(cands) == 1 and cands[0]["concept_id"] == "xx_provision" and cands[0]["corrected_sign"] == "+"


def test_ambiguity_multiple_candidates_defers_never_guesses():
    # two equal '-' contras where flipping EITHER alone cancels → the detector returns BOTH → the caller defers
    store = _fake_store([("c1", "-", -100.0), ("c2", "-", -100.0)])
    leaf_amounts = {"al": 100.0, "el": 100.0, "c1": -100.0, "c2": -100.0}   # tle = 100 +100 +100 = 300 → off by −200
    diff = balance_difference(store, derive_statement(store, "bs", leaf_amounts)[0])
    cands = diagnose_balance(store, "bs", leaf_amounts, diff)
    assert len(cands) == 2                                   # >1 → the caller (build/gate) defers, never auto-picks
    assert {c["concept_id"] for c in cands} == {"c1", "c2"}


def test_none_when_no_contra_flip_cancels():
    store = _fake_store([("c1", "-", -100.0)])
    leaf_amounts = {"al": 999.0, "el": 100.0, "c1": -100.0}   # a real imbalance no single sign-flip can fix
    diff = balance_difference(store, derive_statement(store, "bs", leaf_amounts)[0])
    assert diagnose_balance(store, "bs", leaf_amounts, diff) == []   # 0 candidates → stays flagged (honest)


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
