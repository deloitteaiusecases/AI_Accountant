"""Phase 1 — the master FS structure capability: GATE 0, map-into-seed, render-subset, comparatives,
coherent extension, three-store isolation. AI calls use a fake client (no network); the model accuracy
isn't unit-tested — the no-silent-guess / provenance / placement invariants are.

    python tests/test_master_fs.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.notelib.recon import FaceTB, TBAccount                        # noqa: E402
from ai_accountant.master_fs import (AI_ASSUMED, AI_CONFIRMED, AuditRecord, ClientMappingStore,  # noqa: E402
                                     MappingRecord, MasterConcept, PREPARER, ProvenanceStore,
                                     apply_mapping_decisions, balance_difference, concept_for_label,
                                     confirm_master_extension, coverage_leaves, derive_statement,
                                     leaf_amounts, load_master_store, load_registry, orphan_leaves,
                                     propose_account_concepts, propose_master_extension,
                                     record_preparer_mappings, record_sign_convention,
                                     render_comparative, render_statement,
                                     topo_order, validate_csv, validate_engine_meta, validate_rollups,
                                     validate_seed)

ROOT = Path(__file__).resolve().parent.parent
SEED_JSON = ROOT / "seeds" / "master_fs_structure_seed.json"
SEED_XLSX = ROOT / "seeds" / "Master_FS_Structure_Seed_AlJazira_SAAB.xlsx"
SEED_CSV = ROOT / "seeds" / "master_fs_structure_seed.csv"
ROLLUPS = ROOT / "Formulas" / "master_fs_rollups_authored.json"
TS = "2026-06-11T00:00:00Z"


def _store():
    return load_master_store(str(SEED_JSON))


def _loans(store):
    return next(c for c in store.concepts.values()
                if "financing" in c.canonical_concept.lower() and c.statement == "balance_sheet")


class _FakeClient:
    def __init__(self, proposals):
        self._p = proposals

    def complete_json(self, prompt, system=None, max_retries=3):
        assert "amount" not in prompt.lower() or "no amount" in prompt.lower()   # labels-only, no figures
        return {"proposals": self._p}


# ---- GATE 0 ----------------------------------------------------------------------------------------
def test_gate0_seed_matches_approved_xlsx_with_alias_pairing():
    if not (SEED_JSON.exists() and SEED_XLSX.exists()):
        print("[skip] seed files not present")
        return
    assert validate_seed(str(SEED_JSON), str(SEED_XLSX)) == []      # faithful, including alias pairing
    assert validate_csv(str(SEED_JSON), str(SEED_CSV)) == []        # the flat copy doesn't drift

    # the pairing check has TEETH: swap aljazira/saab on one both_naming_differs concept → caught
    d = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    for r in d["statements"]["balance_sheet"]:
        if r["presence"] == "both_naming_differs":
            a = r["label_aliases"]
            a["aljazira"], a["saab"] = a["saab"], a["aljazira"]
            break
    p = Path(tempfile.mktemp(suffix=".json"))
    p.write_text(json.dumps(d), encoding="utf-8")
    problems = validate_seed(str(p), str(SEED_XLSX))
    p.unlink()
    assert any("PAIRING" in x for x in problems)                   # the swap is caught, not waved through


def test_master_holds_no_amounts_structurally():
    names = {f.name for f in dataclasses.fields(MasterConcept)}
    assert not (names & {"amount", "value", "figure", "balance", "closing"})   # structure only, by design


# ---- map-into-seed, BOTH directions ---------------------------------------------------------------
def test_map_into_seed_signal_success_and_conservatism():
    store = _store()
    loans = _loans(store)
    ms, au = ClientMappingStore(), ProvenanceStore()
    items = [("A1", "Financing, net"), ("A2", "Loans and advances, net"), ("A9", "Misc 0099")]
    fake = _FakeClient([
        {"code": "A1", "line": loans.canonical_concept, "confidence": "high", "evidence": "financing"},
        {"code": "A2", "line": loans.canonical_concept, "confidence": "high", "evidence": "loans/advances"},
        {"code": "A9", "line": "unsure", "confidence": "low", "evidence": "too vague"}])
    props = propose_account_concepts(items, store, client=fake)
    apply_mapping_decisions(props, store, client_id="bankX", decisions={"A1": "confirm", "A2": "confirm"},
                            mapping_store=ms, audit=au, approver="rev", at=TS)
    # (a) signal success — two differently-labelled accounts → the ONE loans/financing concept
    assert ms.concept_of("bankX", "A1") == loans.concept_id
    assert ms.concept_of("bankX", "A2") == loans.concept_id
    # (b) conservatism — the unsure line stays UNMAPPED + flagged, never force-mapped
    a9 = ms.mapping("bankX")["A9"]
    assert a9.concept_id is None and a9.flagged_reason and a9.provenance != AI_CONFIRMED


def test_assume_is_distinct_from_confirm():
    store = _store()
    loans = _loans(store)
    ms, au = ClientMappingStore(), ProvenanceStore()
    fake = _FakeClient([{"code": "A1", "line": loans.canonical_concept, "confidence": "high", "evidence": "x"}])
    props = propose_account_concepts([("A1", "Financing, net")], store, client=fake)
    apply_mapping_decisions(props, store, client_id="bankX", decisions={"A1": "assume"},
                            mapping_store=ms, audit=au, approver="rev", at=TS)
    assert ms.mapping("bankX")["A1"].provenance == AI_ASSUMED      # accepted unverified → flagged state
    assert AI_ASSUMED != AI_CONFIRMED                              # never the same state


# ---- render the populated subset, master order, client labels -------------------------------------
def _map_loans(store, client_id, ms, au):
    loans = _loans(store)
    fake = _FakeClient([
        {"code": "A1", "line": loans.canonical_concept, "confidence": "high", "evidence": "x"},
        {"code": "A2", "line": loans.canonical_concept, "confidence": "high", "evidence": "x"}])
    props = propose_account_concepts([("A1", "Financing"), ("A2", "Loans and advances")], store, client=fake)
    apply_mapping_decisions(props, store, client_id=client_id, decisions={"A1": "confirm", "A2": "confirm"},
                            mapping_store=ms, audit=au, approver="rev", at=TS)
    return loans


def test_render_only_populated_lines_plus_derived_spine():
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    loans = _map_loans(store, "bankX", ms, au)
    lines = render_statement(store, ms, "bankX", {"A1": 1000.0, "A2": 2000.0, "A9": 500.0}, "aljazira", "balance_sheet")
    by = {l.concept_id: l for l in lines}
    # the one populated LEAF renders (A9 unmapped → contributes to nothing); summed deterministically
    assert by[loans.concept_id].amount == 3000.0 and not by[loans.concept_id].derived
    assert by[loans.concept_id].label == loans.label_for("aljazira")    # the client's own wording
    # NO other leaf renders (empty leaves still hide) — every non-loans line is derived
    assert all(l.derived for cid, l in by.items() if cid != loans.concept_id)
    # the DERIVED spine is now present and computed deterministically: Total assets = the only asset = 3000
    assert by["bs_total_assets"].amount == 3000.0 and by["bs_total_assets"].derived
    assert by["bs_total_assets"].kind == "total"
    assert "bs_total_liab_equity" in by and by["bs_total_liab_equity"].amount == 0.0   # spine always renders
    # a derived total is never an empty-leaf: it is rendered even at 0; an empty intermediate would hide
    assert len(store.concepts) >= 60


def test_comparative_two_same_client_periods():
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    loans = _map_loans(store, "bankX", ms, au)
    rows = render_comparative(store, ms, "bankX", {"A1": 1000.0, "A2": 2000.0}, {"A1": 900.0, "A2": 1800.0},
                              "aljazira", "balance_sheet")
    r = next(x for x in rows if x.concept_id == loans.concept_id)
    assert r.current == 3000.0 and r.prior == 2700.0               # same client, two periods, two columns


# ---- propose-addition lands with a coherent PLACE -------------------------------------------------
def test_propose_addition_lands_coherently_placed():
    store = _store()
    au = ProvenanceStore()
    fake = _FakeClient([{"code": "Z1", "note_ref": "Investments, net", "face_caption": "Investments, net",
                         "classification": "financial asset", "sign": "Dr", "sub_class": "",
                         "confidence": "high", "evidence": "a held asset"}])
    proposed = propose_master_extension("Z1", "Digital asset holdings, net", "balance_sheet", store, client=fake)
    assert proposed.l0_section == "ASSETS"                          # AI proposed WHERE it sits
    before = len(store.concepts)
    concept = confirm_master_extension(proposed, store, concept_id="bs_digital_assets", approver="rev",
                                       at=TS, audit=au, client_id="bankX")
    # appended AND coherently placed: valid section + a real order slot (renders in the right place)
    assert len(store.concepts) == before + 1
    assert concept.l0_section in store.sections("balance_sheet") and concept.order > 0
    assert concept.provenance == "proposed_confirmed"
    assert any(a.action == "extend_master" and a.target == "bs_digital_assets" for a in au.records)


# ---- three-store isolation ------------------------------------------------------------------------
def test_per_client_mappings_are_isolated():
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    _map_loans(store, "aljazira", ms, au)
    # SAAB maps a DIFFERENT account; AlJazira's mappings must not appear for SAAB
    fake = _FakeClient([{"code": "S1", "line": _loans(store).canonical_concept, "confidence": "high", "evidence": "x"}])
    props = propose_account_concepts([("S1", "Loans and advances")], store, client=fake)
    apply_mapping_decisions(props, store, client_id="saab", decisions={"S1": "confirm"},
                            mapping_store=ms, audit=au, approver="rev", at=TS)
    assert set(ms.mapping("aljazira")) == {"A1", "A2"}
    assert set(ms.mapping("saab")) == {"S1"}                        # disjoint — no leak
    assert ms.concept_of("saab", "A1") is None                     # AlJazira's account invisible to SAAB


# ---- preparer path: the client's own mappings carry provenance=preparer ----------------------------
def test_preparer_mappings_carry_provenance():
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    cash = concept_for_label(store, "Cash and balances with Saudi Central Bank (SAMA)")
    assert cash is not None
    fb = FaceTB()
    fb.accounts.append(TBAccount(code="C1", level="L4", account_type="C", label="Cash",
                                 final_amount=100.0, mapping="Cash and balances with Saudi Central Bank (SAMA)"))
    fb.accounts.append(TBAccount(code="C2", level="L4", account_type="C", label="Mystery",
                                 final_amount=50.0, mapping="Nonexistent caption"))
    unmatched = record_preparer_mappings(fb, store, client_id="aljazira", mapping_store=ms, audit=au,
                                         approver="preparer", at=TS)
    assert ms.mapping("aljazira")["C1"].provenance == PREPARER and ms.concept_of("aljazira", "C1") == cash.concept_id
    assert "C2" in unmatched and ms.concept_of("aljazira", "C2") is None   # unmatched caption flagged, not guessed


def test_export_model_is_honest():
    """The master-FS export model: AI-assumed tagged (line + provenance), present-where-present
    comparatives, findings surfaced, NOT-FINAL conditional on real state. Deterministic (no live call)."""
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    store = _store()
    inv = next(c for c in store.concepts.values() if c.canonical_concept == "Investments, net")
    loans = _loans(store)
    stored = {"client": "x", "model": "m",
              "tb": [{"account": "a1", "label": "Inv", "current": 100, "prior": 90},
                     {"account": "a2", "label": "Loans", "current": 200, "prior": None},     # one period only
                     {"account": "a3", "label": "Sundry", "current": 5, "prior": 5}],
              "mappings": [
                  {"account": "a1", "concept_id": inv.concept_id, "client_label": "Inv",
                   "provenance": "ai_confirmed", "confidence": "high"},
                  {"account": "a2", "concept_id": loans.concept_id, "client_label": "Loans",
                   "provenance": "ai_assumed", "confidence": "medium"},
                  {"account": "a3", "concept_id": None, "client_label": "Sundry",
                   "provenance": "", "flagged_reason": "left open"}], "audit": []}
    m = build_master_fs_export(store, stored, bank="aljazira")
    bs = {l.concept_id: l for l in m.statements["balance_sheet"]}
    assert bs[inv.concept_id].ai_assumed is False and bs[loans.concept_id].ai_assumed is True
    assert bs[loans.concept_id].current == 200 and bs[loans.concept_id].prior is None   # present / absent
    # derived spine lines are NEUTRAL — never tagged ai_assumed / new even amid AI-assumed leaves
    assert bs["bs_total_assets"].derived is True and bs["bs_total_assets"].ai_assumed is False
    assert any(t[3] == "ai_assumed" for t in m.provenance)                              # provenance shows it
    assert any(a == "a3" for a, _, _ in m.findings)                                    # unmapped surfaced
    assert m.not_final is True                                                          # conditional: real state

    # clean case → NOT-FINAL absent (conditional, never always-on). A balanced mini-BS: inv asset == cap.
    cap = next(c for c in store.concepts.values() if c.canonical_concept == "Share capital")
    clean = dict(stored,
                 mappings=[stored["mappings"][0],
                           {"account": "e1", "concept_id": cap.concept_id, "client_label": "Cap",
                            "provenance": "ai_confirmed", "confidence": "high"}],
                 tb=[stored["tb"][0], {"account": "e1", "label": "Cap", "current": 100, "prior": 90}])
    clean_m = build_master_fs_export(store, clean, bank="aljazira")
    assert clean_m.findings == [] and clean_m.not_final is False    # balances, all confirmed → clean


# ---- presentation completeness: the derive pass + the two guards --------------------------------
def test_authored_formula_fidelity():
    """The seed faithfully carries the HUMAN-AUTHORED roll-ups (kind + signed components) — the AI
    never authored these; the derive pass computes exactly what was authored."""
    if not (SEED_JSON.exists() and ROLLUPS.exists()):
        print("[skip] seed/rollups not present")
        return
    assert validate_rollups(str(SEED_JSON), str(ROLLUPS)) == []


def test_derive_rollups_and_sign_convention():
    """Each net/subtotal/total equals its hand-computed value; expenses stored NEGATIVE roll up via '+'."""
    store = _store()
    leaf = {"pl_sci": 4800.0, "pl_sce": -1900.0, "pl_fee_inc": 1300.0, "pl_fee_exp": -100.0,
            "pl_salaries": -2100.0, "pl_dep": -350.0, "pl_impairment": -700.0}
    values, present = derive_statement(store, "income_statement", leaf)
    assert values["pl_net_sci"] == 2900.0                          # 4800 + (−1900)
    assert values["pl_net_fee"] == 1200.0                          # 1300 + (−100)
    assert values["pl_total_inc"] == 4100.0                        # 2900 + 1200
    assert values["pl_total_exp"] == -3150.0                       # all expenses, stored negative
    assert values["pl_net_op"] == 950.0                            # 4100 + (−3150)
    assert values["pl_net_income"] == 950.0                        # nibz (+associate 0) (+zakat 0)(+tax 0)
    # topo order resolves a total that references other totals AFTER them
    order = topo_order(store, "balance_sheet")
    assert order.index("bs_total_liab_equity") > order.index("bs_total_liabilities")
    assert order.index("bs_total_liab_equity") > order.index("bs_total_equity")


def test_bs_totals_derive_and_reference_other_totals():
    store = _store()
    leaf = {"bs_cash": 1000.0, "bs_loans": 4000.0,                 # assets 5000
            "bs_deposits": 3000.0,                                  # liabilities 3000
            "bs_share_cap": 2000.0, "bs_treasury": 500.0}           # equity 2000 − 500 = 1500
    values, _ = derive_statement(store, "balance_sheet", leaf)
    assert values["bs_total_assets"] == 5000.0
    assert values["bs_total_liabilities"] == 3000.0
    assert values["bs_total_equity"] == 1500.0                     # treasury authored as a MINUS
    assert values["bs_total_liab_equity"] == 4500.0                # references the two totals (3000 + 1500)
    assert balance_difference(store, values) == 500.0              # 5000 − 4500 (does NOT balance here)


def test_orphan_guard_transitive_and_zero_orphan_seed():
    """The closure walk is TRANSITIVE: gross P&L leaves reach pl_net_income THROUGH the net-lines; and
    every canonical seed leaf (bar declared memos) sits in exactly one section total — zero orphans."""
    store = _store()
    cov = coverage_leaves(store, "income_statement")
    for cid in ("pl_sci", "pl_sce", "pl_fee_inc", "pl_fee_exp"):   # gross leaves, two levels deep
        assert cid in cov                                          # reached via pl_net_sci / pl_net_fee
    assert "pl_eps" not in cov and "pl_eps" in store.memo_leaves()  # memo line, legitimately uncovered (seed-declared)
    # BUILD-TIME ASSERTION: the canonical seed is complete — no populated leaf could orphan
    for st in ("balance_sheet", "income_statement", "comprehensive_income"):
        leaves = {c.concept_id for c in store.statement(st) if not c.is_computed}
        assert orphan_leaves(store, st, leaves) == []
    # each leaf sits in EXACTLY one section total's closure (not double-counted)
    sect_totals = {"ASSETS": "bs_total_assets", "LIABILITIES": "bs_total_liabilities", "EQUITY": "bs_total_equity"}
    for leaf_c in (c for c in store.statement("balance_sheet") if not c.is_computed):
        hits = [t for sec, t in sect_totals.items()
                if leaf_c.concept_id in _closure(store, t)]
        assert len(hits) == 1, f"{leaf_c.concept_id} in {hits}"


def _closure(store, total_id):
    acc = set()
    def walk(cid):
        c = store.get(cid)
        if c is None:
            return
        if not c.is_computed:
            acc.add(cid); return
        for _s, dep in c.components:
            walk(dep)
    walk(total_id)
    return acc


def test_orphan_guard_catches_unattached_ai_added_leaf():
    """An AI-added leaf with section+order but NO total-membership is SURFACED, never silently dropped
    (the demo Zakat-extension class). The interactive 'attach to a total' step is parked (slice 10)."""
    store = _store()
    store.add(MasterConcept(concept_id="x_new_payable", statement="balance_sheet", l0_section="LIABILITIES",
                            l1_group=None, canonical_concept="Some new payable", label_aliases={},
                            presence="client_added", order=999, provenance="proposed_unconfirmed"))  # kind=leaf
    populated = {"bs_deposits", "x_new_payable"}                   # the new leaf is populated but unattached
    orphans = orphan_leaves(store, "balance_sheet", populated)
    assert orphans == ["x_new_payable"]                            # caught — would understate Total liabilities


def test_balance_check_both_directions():
    """Truth-teller: a balanced TB → no balance finding; an unbalanced TB → a finding, never blocked."""
    store = _store()
    balanced = {"bs_cash": 1000.0, "bs_deposits": 600.0, "bs_share_cap": 400.0}     # 1000 == 600 + 400
    v1, _ = derive_statement(store, "balance_sheet", balanced)
    assert balance_difference(store, v1) == 0.0
    unbalanced = {"bs_cash": 1000.0, "bs_deposits": 600.0, "bs_share_cap": 300.0}   # 1000 vs 900
    v2, _ = derive_statement(store, "balance_sheet", unbalanced)
    assert balance_difference(store, v2) == 100.0                   # surfaced as the difference, render still happens


def test_unbalanced_export_emits_exactly_one_balance_finding():
    """A deliberately-unbalanced TB → EXACTLY one balance finding (proves the check fires, not cosmetic)."""
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    store = _store()
    cash = next(c for c in store.concepts.values() if c.canonical_concept.startswith("Cash and balances"))
    cap = next(c for c in store.concepts.values() if c.canonical_concept == "Share capital")
    stored = {"client": "x", "model": "m",
              "tb": [{"account": "a1", "label": "Cash", "current": 1000, "prior": 1000},
                     {"account": "e1", "label": "Cap", "current": 300, "prior": 300}],   # 1000 != 300
              "mappings": [{"account": "a1", "concept_id": cash.concept_id, "client_label": "Cash",
                            "provenance": "preparer", "confidence": ""},
                           {"account": "e1", "concept_id": cap.concept_id, "client_label": "Cap",
                            "provenance": "preparer", "confidence": ""}]}
    m = build_master_fs_export(store, stored, bank="aljazira")
    bal = [f for f in m.findings if f[0] == "balance check"]
    assert len(bal) == 1 and "700" in bal[0][2]                     # difference 1000 − 300 = 700, surfaced


def test_oci_two_bucket_subheadings_carried():
    """The OCI reclassify / non-reclassify buckets (l1_group) are carried to the render so the export
    can emit the sub-headings — both banks' OCI has them and ours used to flatten them."""
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    fake = _FakeClient([
        {"code": "O1", "line": "Net change in fair value of FVOCI equity instruments", "confidence": "high", "evidence": "x"},
        {"code": "O2", "line": "Net change in fair value of FVOCI debt instruments", "confidence": "high", "evidence": "x"}])
    props = propose_account_concepts([("O1", "FVOCI equity"), ("O2", "FVOCI debt")], store, client=fake)
    apply_mapping_decisions(props, store, client_id="bankX", decisions={"O1": "confirm", "O2": "confirm"},
                            mapping_store=ms, audit=au, approver="rev", at=TS)
    lines = render_statement(store, ms, "bankX", {"O1": 90.0, "O2": 220.0}, "aljazira", "comprehensive_income")
    groups = {l.l1_group for l in lines if l.l1_group}
    assert any("NOT be reclassified" in g for g in groups)          # equity bucket
    assert any(("WILL be reclassified" in g) or ("will be reclassified" in g.lower()) for g in groups)  # debt bucket


# ---- Slice A: the engine is seed-driven (a new seed needs ZERO engine-code changes) --------------
import re                                                                              # noqa: E402
import warnings                                                                        # noqa: E402

REG = ROOT / "seeds" / "registry.json"
ENGINE_FILES = ["ai_accountant/master_fs/derive.py", "ai_accountant/master_fs/mapping.py",
                "ai_accountant/master_fs/render.py", "ai_accountant/master_fs/validate.py",
                "ai_accountant/master_fs/model.py", "ai_accountant/master_fs/orchestrator.py",
                "ai_accountant/master_fs/detect.py", "ai_accountant/master_fs/notes.py",
                "ai_accountant/master_fs/face_split.py", "ai_accountant/tb_ingest/bs_split.py",
                "ai_accountant/reporting/master_fs_export.py"]
_BANK_VOCAB = ["Sukuk", "Special commission", "Tier 1", "Murabaha", "Financing", "Customers' deposits"]


def _dump_model(m):
    return {"bank": m.bank, "unit": m.unit, "period_current": m.period_current, "period_prior": m.period_prior,
            "not_final": m.not_final,
            "statements": {st: [{"concept_id": l.concept_id, "label": l.label, "section": l.section,
                "current": l.current, "prior": l.prior, "ai_assumed": l.ai_assumed, "new_concept": l.new_concept,
                "derived": l.derived, "kind": l.kind, "l1_group": l.l1_group} for l in lines]
                for st, lines in m.statements.items()},
            "provenance": [list(t) for t in m.provenance], "findings": [list(t) for t in m.findings],
            "extensions": [list(t) for t in m.extensions]}


def test_no_regression_replay_byte_identical():
    """LEG 1: replaying the 4 frozen stored results through the seed-driven engine reproduces the
    pre-refactor model byte-for-byte — the bank behaviour did not change."""
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    fix = ROOT / "tests" / "fixtures" / "regression"
    if not fix.exists():
        print("[skip] regression baselines not present"); return
    for src, bank in (("master_fs_nomap", None), ("master_fs_premap", None),
                      ("master_fs_saab_nomap", "saab"), ("master_fs_saab_premap", "saab")):
        stored = json.loads((ROOT / "exports" / f"{src}.json").read_text(encoding="utf-8"))
        m = build_master_fs_export(load_master_store(), stored, bank=bank,
                                   period_current="31 December 2024", period_prior="31 December 2023")
        now = json.dumps(_dump_model(m), ensure_ascii=False, indent=2, sort_keys=True)
        base = (fix / f"{src}.model.json").read_text(encoding="utf-8")
        assert now == base, f"{src} model drifted from baseline"


def test_assembled_bank_prompt_equals_baseline():
    """LEG 2: the bank prompt assembled from the seed's injected pieces == the original literal string."""
    import ai_accountant.master_fs.mapping as MAP
    fix = ROOT / "tests" / "fixtures" / "regression"
    if not fix.exists():
        print("[skip] baselines not present"); return
    store = _store()
    assert MAP._assemble_master_system(store) == (fix / "prompt_master_fs_system.txt").read_text(encoding="utf-8")
    assert MAP._assemble_extension_system(store) == (fix / "prompt_extension_system.txt").read_text(encoding="utf-8")


def test_engine_files_grep_clean():
    """No ARCHETYPE FACT survives as a literal in any engine file: archetype name, concept_id (incl.
    carry-leaf id/from, which match the concept_id pattern), section name, statement key, statement
    title, or banking vocabulary. EXEMPT framework invariants (must stay fixed, do NOT de-hardcode):
    the model pin, the sign convention, schema FIELD names, and the propose-confirm-store/labels-only
    contract — none of which match these patterns."""
    arche = re.compile(r"aljazira|saab", re.I)
    cid = re.compile(r"\b(bs_|pl_|oci_|tc_)[a-z]\w*")             # concept_ids incl. carry-leaf id/from
    stmt_key = re.compile(r"\b(balance_sheet|income_statement|comprehensive_income)\b")
    stmt_title = re.compile(r"Balance Sheet|Income Statement|Statement of Comprehensive Income")
    section = re.compile(r"\b(ASSETS|LIABILITIES|EQUITY|OPERATING_INCOME|OPERATING_EXPENSES|RESULT|"
                         r"COMPREHENSIVE_INCOME|NON_CURRENT_ASSETS|CURRENT_ASSETS|NON_CURRENT_LIABILITIES|"
                         r"CURRENT_LIABILITIES|RESOURCES|OBLIGATIONS|REVENUE|OTHER_INCOME_EXPENSE)\b")
    for f in ENGINE_FILES:
        src = (ROOT / f).read_text(encoding="utf-8")
        assert not arche.search(src), f"{f}: archetype name literal"
        assert not cid.search(src), f"{f}: seed-specific concept_id / carry-leaf id literal"
        assert not stmt_key.search(src), f"{f}: statement-key literal (must come from the seed)"
        assert not stmt_title.search(src), f"{f}: statement-title literal (must come from the seed)"
        assert not section.search(src), f"{f}: section-name literal (must come from the seed)"
        for term in _BANK_VOCAB:
            assert term not in src, f"{f}: banking vocabulary {term!r} (belongs in seed mapping_hints)"
    # detection thresholds are CONFIG (registry `detect_thresholds`), never bare literals in the verdict path
    for f in ("ai_accountant/master_fs/detect.py", "ai_accountant/master_fs/mapping.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        for num in ("0.15", "0.10", "0.30"):
            assert num not in src, f"{f}: threshold literal {num} (must come from the registry)"


def test_movement_builder_carries_no_note_vocab():
    """Slice N1: the GENERIC roll-forward builder names no note-specific vocabulary — the caption, the
    contra's charge name, the exempt class are all injected. Same discipline as the engine carrying no
    archetype literals. The specific words (depreciation/Land for PP&E, amortization/Goodwill for
    intangibles) live ONLY in each note's config + wrapper (ppe.py / the seed), never the mechanism."""
    src = (ROOT / "ai_accountant/master_fs/notelib/movement.py").read_text(encoding="utf-8")
    forbidden = re.compile(r"depreciat|amorti[sz]|\bland\b|property,\s*plant|\bppe\b|goodwill", re.I)
    hit = forbidden.search(src)
    assert hit is None, f"movement_note.py carries note-specific vocab {hit.group()!r} (belongs in the note's config)"


def test_registry_resolution_and_telecom_seed_drives_engine():
    """The real telecom seed (tc_* ids, current/non-current sections) loads via the registry and
    derives/renders with ZERO engine edits beyond the Task-1 validator — the headline seed-driven proof."""
    if not REG.exists() or "telecom_mobily" not in load_registry():
        print("[skip] telecom_mobily not registered"); return
    store = load_master_store(seed_id="telecom_mobily")
    assert store.master_id == "telecom_mobily"
    assert store.sections("balance_sheet") == ["NON_CURRENT_ASSETS", "CURRENT_ASSETS", "EQUITY",
                                               "NON_CURRENT_LIABILITIES", "CURRENT_LIABILITIES"]  # NOT bank sections
    ms = ClientMappingStore()
    leaves = {"tc_ppe": 600.0, "tc_cash": 100.0,            # NCA 600, CA 100 -> assets 700
              "tc_share_cap": 400.0,                          # equity 400
              "tc_borrowings_nc": 200.0, "tc_accounts_payable": 100.0}  # NCL 200 + CL 100 -> liab 300
    for acct, cid in [(c, c) for c in leaves]:
        ms.put("telco", MappingRecord(account=acct, concept_id=cid, client_label=acct,
                                      provenance="preparer", master_id=store.master_id))
    lines = {l.concept_id: l for l in render_statement(store, ms, "telco", leaves, None, "balance_sheet")}
    assert lines["tc_total_nca"].amount == 600.0 and lines["tc_total_ca"].amount == 100.0
    assert lines["tc_total_assets"].amount == 700.0 and lines["tc_total_assets"].derived  # subtotal->total
    assert lines["tc_total_oe"].amount == 700.0                       # equity+liab 400+300 == assets 700
    assert balance_difference(store, derive_statement(store, "balance_sheet", leaves)[0]) == 0.0


def test_hint_swap_telecom_prompt_is_seed_driven_not_bank():
    """Positive proof the vocabulary is seed-driven: the telecom prompt carries THIS seed's own hints,
    the bank's hint block is ABSENT, and bank-DISTINCTIVE FS-line vocabulary does not leak. (Generic
    Islamic-finance words like 'Murabaha' may legitimately appear — the telecom holds short-term
    Murabaha placements — because the SEED author put them there, not because code hardcodes them.)"""
    import ai_accountant.master_fs.mapping as MAP
    if not REG.exists() or "telecom_mobily" not in load_registry():
        print("[skip] telecom_mobily not registered"); return
    bank = load_master_store(seed_id="ksa_bank")
    telco = load_master_store(seed_id="telecom_mobily")
    asm = MAP._assemble_master_system(telco)
    assert "TELECOM" in asm.upper()
    assert telco.prompts()["mapping_hints"] in asm                  # the prompt reflects the active seed
    assert bank.prompts()["mapping_hints"] not in asm               # the bank's hint block is absent
    for term in ("Special commission", "Customers' deposits", "Additional Tier 1"):
        assert term not in asm, f"bank-distinctive term {term!r} leaked into the telecom prompt"


def test_load_fails_loud_on_dangling_id():
    """A seed declaring a coverage_total / balance_check / memo id that is not a concept BLOCKS at load."""
    d = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    d["engine"]["statements"][0]["coverage_totals"] = ["bs_total_assets", "bs_NONEXISTENT"]
    p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(d), encoding="utf-8")
    try:
        raised = False
        try:
            load_master_store(str(p))
        except ValueError as e:
            raised = True
            assert "bs_NONEXISTENT" in str(e)
        assert raised, "dangling coverage_total id was not caught at load"
    finally:
        p.unlink()


def test_load_fails_loud_on_dangling_component():
    """A bad id INSIDE a concept's `components` would silently contribute 0 to a subtotal — it must now
    BLOCK at load, same as the other dangling-id checks. Also a bad sign is rejected."""
    base = json.loads(SEED_JSON.read_text(encoding="utf-8"))

    def _load_corrupted(mutate):
        d = json.loads(json.dumps(base))
        mutate(d)
        p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(d), encoding="utf-8")
        try:
            load_master_store(str(p))
            return None
        except ValueError as e:
            return str(e)
        finally:
            p.unlink()

    def bad_id(d):
        for c in d["statements"]["balance_sheet"]:
            if c.get("components"):
                c["components"][0] = ["+", "bs_NONEXISTENT"]
                return
    msg = _load_corrupted(bad_id)
    assert msg is not None and "bs_NONEXISTENT" in msg, "dangling component id was not caught at load"

    def bad_sign(d):
        for c in d["statements"]["balance_sheet"]:
            if c.get("components"):
                c["components"][0] = ["*", c["components"][0][1]]
                return
    assert _load_corrupted(bad_sign) is not None, "invalid component sign was not caught at load"


def test_validate_engine_meta_catches_section_drift():
    d = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    d["engine"]["statements"][0]["sections"] = ["ASSETS", "LIABILITIES"]    # dropped EQUITY → drift
    problems = validate_engine_meta(d)
    assert any("declared sections" in p for p in problems)


def test_cross_seed_id_collision_warns_not_fails():
    """Two registry seeds declaring the same concept_id → WARN (never fail). Guards Slice-B detection."""
    reg = {"masters": [{"id": "a", "label": "A", "seed_path": "seeds/master_fs_structure_seed.json",
                        "rollups_path": "x"},
                       {"id": "b", "label": "B", "seed_path": "seeds/master_fs_structure_seed.json",
                        "rollups_path": "x"}]}                              # same seed → guaranteed overlap
    p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(reg), encoding="utf-8")
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_registry(str(p))
        assert any("declared by BOTH masters" in str(x.message) for x in w)
    finally:
        p.unlink()


def test_telecom_mobily_published_riyal_exact():
    """RIYAL-EXACT structure/formula guard: feed Mobily's published FY2024/FY2023 face values into the
    telecom seed (tc_np is a CARRY-leaf, populated from the P&L net-profit total — NOT an input), derive,
    and assert every printed subtotal/total matches to the riyal and the balance check == 0, both years."""
    fix = ROOT / "tests" / "fixtures" / "regression" / "telecom_mobily_published_fixture.json"
    if not fix.exists() or "telecom_mobily" not in load_registry():
        print("[skip] published fixture / registry not present"); return
    data = json.loads(fix.read_text(encoding="utf-8"))
    store = load_master_store(seed_id="telecom_mobily")
    from ai_accountant.master_fs import apply_carries
    for year in ("2024", "2023"):
        leaves = {k: float(v) for k, v in data["leaves"][year].items() if k != "tc_np"}   # tc_np is carried
        carried = apply_carries(store, dict(leaves))
        exp = data["expected_totals"][year]
        assert round(carried["tc_np"]) == round(exp["tc_net_profit"]), f"{year}: carry tc_np != net profit"
        values = {}
        for st in store.statement_keys():
            st_leaves = {k: v for k, v in carried.items() if store.get(k) and store.get(k).statement == st}
            values.update(derive_statement(store, st, st_leaves)[0])
        for cid, want in exp.items():
            assert round(values.get(cid, 0)) == round(want), f"{year} {cid}: {values.get(cid)} != {want}"
        bs = {k: v for k, v in carried.items() if store.get(k) and store.get(k).statement == "balance_sheet"}
        assert balance_difference(store, derive_statement(store, "balance_sheet", bs)[0]) == 0.0


def test_client_mappings_scoped_by_master_id():
    """A client_id under two masters does not silently merge — leak-safe (raise unless master_id given)."""
    ms = ClientMappingStore()
    ms.put("c", MappingRecord(account="x", concept_id="bs_cash", client_label="x",
                              provenance="preparer", master_id="ksa_bank"))
    ms.put("c", MappingRecord(account="x", concept_id="tc_cash", client_label="x",
                              provenance="preparer", master_id="telecom_stub"))
    assert ms.concept_of("c", "x", master_id="ksa_bank") == "bs_cash"
    assert ms.concept_of("c", "x", master_id="telecom_stub") == "tc_cash"
    try:
        ms.mapping("c"); assert False, "ambiguous client_id should raise"
    except ValueError:
        pass


# ---- Slice A.1: carry-leaves + mapper hardening --------------------------------------------------
def test_oci_carry_leaf_populated_from_pl_net_income():
    """The OCI net-income line is CARRIED from the P&L net-profit total (deterministic, no AI), so Total
    CI = OCI + net income — the correction the carry exists for (bank's old Total CI omitted net income)."""
    store = _store()
    ms = ClientMappingStore()
    for acct, cid in (("a1", "pl_sci"), ("a2", "oci_fvoci_eq")):
        ms.put("x", MappingRecord(account=acct, concept_id=cid, client_label=acct,
                                  provenance="preparer", master_id=store.master_id))
    tb = {"a1": 1000.0, "a2": 50.0}
    isl = {l.concept_id: l for l in render_statement(store, ms, "x", tb, None, "income_statement")}
    oci = {l.concept_id: l for l in render_statement(store, ms, "x", tb, None, "comprehensive_income")}
    net = isl["pl_net_income"].amount
    assert "oci_ni" in oci and oci["oci_ni"].amount == net                # carried from the P&L total
    assert oci["oci_total_ci"].amount == round(net + oci["oci_total_oci"].amount, 2)  # Total CI now includes it


def test_block_amount_on_computed_or_carry_concept():
    """BLOCK-don't-absorb: a (preparer/manual) mapping that resolves to a computed total OR a carry-leaf
    is left OPEN with a finding — never placed on the derived line, never silently dropped."""
    store = _store()
    ms, au = ClientMappingStore(), ProvenanceStore()
    subtotal = next(c for c in store.concepts.values() if c.canonical_concept == "Total operating income (subtotal)")
    carry = store.get("oci_ni")
    fb = FaceTB()
    fb.accounts.append(TBAccount(code="C1", level="L4", account_type="C", label="x",
                                 final_amount=100.0, mapping=subtotal.canonical_concept))     # a computed total
    fb.accounts.append(TBAccount(code="C2", level="L4", account_type="C", label="y",
                                 final_amount=50.0, mapping=carry.canonical_concept))         # a carry-leaf
    unmatched = record_preparer_mappings(fb, store, client_id="x", mapping_store=ms, audit=au, approver="p", at=TS)
    assert "C1" in unmatched and ms.concept_of("x", "C1") is None         # not placed on the subtotal
    assert "C2" in unmatched and ms.concept_of("x", "C2") is None         # not placed on the carry leaf
    assert "computed/carry" in ms.mapping("x")["C1"].flagged_reason


def test_candidate_list_excludes_computed_and_carry():
    """propose_account_concepts offers INPUT LEAVES only — never a subtotal/total/net or a carry-leaf."""
    store = _store()
    captured = {}

    class _Capture:
        def complete_json(self, prompt, system=None, max_retries=3):
            captured["prompt"] = prompt
            return {"proposals": []}
    propose_account_concepts([("A1", "x")], store, client=_Capture())
    cand = captured["prompt"]
    for c in store.concepts.values():
        if c.is_computed or c.concept_id in store.carry_leaf_ids():
            assert c.canonical_concept not in cand, f"{c.concept_id} offered as a mapping candidate"
    assert store.get("bs_cash").canonical_concept in cand                 # a real input leaf IS offered


def test_load_fails_loud_on_bad_carry_leaf():
    base = json.loads(SEED_JSON.read_text(encoding="utf-8"))

    def _corrupt(mutate):
        d = json.loads(json.dumps(base)); mutate(d["engine"])
        p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(d), encoding="utf-8")
        try:
            load_master_store(str(p)); return ""
        except ValueError as e:
            return str(e)
        finally:
            p.unlink()
    assert "carry_leaf id" in _corrupt(lambda e: e.__setitem__("carry_leaves", [{"id": "NOPE", "from": "pl_net_income"}]))
    assert "kind=leaf" in _corrupt(lambda e: e.__setitem__("carry_leaves", [{"id": "pl_net_income", "from": "pl_net_income"}]))
    assert "from" in _corrupt(lambda e: e.__setitem__("carry_leaves", [{"id": "oci_ni", "from": "NOPE"}]))


# ---- Slice B: archetype detection (propose -> human-confirm -> fail-loud) -------------------------
class _ArchetypeClient:
    def __init__(self, per_label, absent=None):
        self.per_label, self.absent, self.prompt = per_label, absent or {}, None

    def complete_json(self, prompt, system=None, max_retries=3):
        self.prompt = prompt
        assert "amount" not in prompt.lower() or "no amounts" in prompt.lower()   # labels-only
        return {"per_label": self.per_label, "absent": self.absent}


def test_archetype_verdict_conservatism_blocks_the_hard_cases():
    """Conservatism by construction: a winner needs high-top AND clear-margin AND a weak runner-up;
    each of the three ambiguous cases lands in UNSURE -> BLOCK with no seed selected."""
    from ai_accountant.master_fs import archetype_verdict, load_detect_thresholds
    th = load_detect_thresholds()
    fps = {"ksa_bank": {"label": "Bank"}, "telecom_mobily": {"label": "Telecom"}}
    items = lambda n: [(str(i), "x") for i in range(n)]
    pl = lambda b, t: ([{"label": "L", "fits": ["ksa_bank"]} for _ in range(b)]
                       + [{"label": "L", "fits": ["telecom_mobily"]} for _ in range(t)])
    assert archetype_verdict(pl(12, 0), {}, items(30), fps, th).verdict == "propose"      # clear winner
    nt = archetype_verdict(pl(6, 5), {}, items(30), fps, th)                               # 0.20 vs 0.17
    bf = archetype_verdict(pl(2, 1), {}, items(30), fps, th)                               # top 0.07 < floor
    mh = archetype_verdict(pl(12, 11), {}, items(30), fps, th)                             # both >= high_bar
    assert (nt.verdict, nt.block_reason, nt.seed_id) == ("unsure", "near_tie", None)
    assert (bf.verdict, bf.block_reason, bf.seed_id) == ("unsure", "below_floor", None)
    assert (mh.verdict, mh.block_reason, mh.seed_id) == ("unsure", "multi_high", None)
    assert nt.finding and "near_tie" in nt.finding and "Bank" in nt.finding   # ranked scores in the finding


def test_propose_archetype_wiring_and_no_amounts():
    """propose_archetype assembles a labels-only request, parses the model's per-label fit, and returns a
    PROPOSAL via the deterministic verdict. Amounts never enter the request."""
    if "telecom_mobily" not in load_registry():
        print("[skip] telecom_mobily not registered"); return
    from ai_accountant.master_fs import load_all_masters, propose_archetype
    stores = load_all_masters()
    items = [("1001", "Customers deposits"), ("1002", "Special commission income"), ("1003", "Cash")]
    fits = [{"label": "Customers deposits", "fits": ["ksa_bank"]},
            {"label": "Special commission income", "fits": ["ksa_bank"]},
            {"label": "Cash", "fits": ["ksa_bank", "telecom_mobily"]}]          # 2 discriminating bank, 1 generic
    fc = _ArchetypeClient(fits)
    prop = propose_archetype(items, stores, client=fc)
    assert prop.verdict == "propose" and prop.seed_id == "ksa_bank"             # 2/3 bank, telecom 0
    assert any(m[0] == "Customers deposits" for m in prop.ranked[0].matched)    # concrete evidence
    assert "1,200,000" not in fc.prompt and "1200000" not in fc.prompt          # no amount token leaked


def test_confirm_archetype_explicit_choice_reuses_provenance():
    """Human-confirm REQUIRES an explicit chosen_seed_id and reuses AI_CONFIRMED / preparer_override."""
    from ai_accountant.master_fs import confirm_archetype, ArchetypeProposal
    au = ProvenanceStore()
    propose = ArchetypeProposal(verdict="propose", seed_id="ksa_bank")
    assert confirm_archetype(propose, "ksa_bank", approver="rev", at=TS, audit=au) == "ksa_bank"
    assert any(r.action == "confirm_archetype" and r.provenance == AI_CONFIRMED for r in au.records)
    au2 = ProvenanceStore()                                                     # after UNSURE, human picks one
    unsure = ArchetypeProposal(verdict="unsure", seed_id=None, block_reason="near_tie")
    confirm_archetype(unsure, "telecom_mobily", approver="rev", at=TS, audit=au2)
    assert any(r.provenance == "preparer_override" for r in au2.records)
    try:
        confirm_archetype(propose, "not_a_seed", approver="rev", at=TS); assert False
    except ValueError:
        pass


def test_generate_master_fs_refuses_without_confirmed_seed_id():
    """The orchestrator guard: an unsure detection (no seed_id) can NEVER silently route to a default."""
    from ai_accountant.master_fs import generate_master_fs
    for bad in (None, ""):
        try:
            generate_master_fs({"client": "x", "tb": [], "mappings": []}, seed_id=bad, client="x")
            assert False, "generate_master_fs accepted a falsy seed_id"
        except ValueError as e:
            assert "confirmed seed_id" in str(e)


# ---- Slice N0: note-attachment (PP&E) re-anchored to a master concept ----------------------------
import dataclasses as _dc  # noqa: E402


@_dc.dataclass
class _Leaf:
    gl_account: str
    opening: float
    closing: float
    movement_by_ref: dict = _dc.field(default_factory=dict)


def _ppe_fixture(mutate=None):
    fx = json.loads((ROOT / "tests" / "fixtures" / "regression" / "ppe_synthetic_gl.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(fx)
    from ai_accountant.master_fs.notelib.propose import ConfirmedPPEAccount
    leaves = [_Leaf(d["gl_account"], d["opening"], d["closing"], dict(d["movement_by_ref"])) for d in fx["leaves"]]
    confirmed = {a: ConfirmedPPEAccount(c, r, "seed", TS) for a, (c, r) in fx["confirmed"].items()}
    return fx, leaves, confirmed


def _ppe_master(concept_value):
    store = load_master_store()                                    # bank seed declares the bs_ppe note
    ms = ClientMappingStore()
    ms.put("demo", MappingRecord(account="9999", concept_id="bs_ppe", client_label="PP&E",
                                 provenance="preparer", master_id=store.master_id))
    return store, ms, {"9999": float(concept_value)}


def test_ppe_note_attaches_reconciles_and_sign_clean():
    """The passing case: GL roll-forward builds by class, Land is cost-only (exempt), the note RECONCILES
    to the master concept's value, and the recorded sign convention passes."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention
    fx, leaves, confirmed = _ppe_fixture()
    store, ms, tb = _ppe_master(fx["concept_value"])
    conv = record_sign_convention("demo", approver="rev", at=TS)
    note, anchor, sign = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed, sign_convention=conv)
    assert note.total_nbv == fx["expected"]["total_nbv"] and note.nbv_by_class == fx["expected"]["by_class"]
    assert anchor.gap == 0.0 and anchor.status() == "BUILT" and note.tie_ok        # reconciles to the concept
    assert not any(s.missing_depreciation for s in note.sections)                  # Land exempt, others have dep
    assert sign == []                                                              # convention recorded & honoured


def test_ppe_note_blocks_when_not_reconciling_to_concept():
    """Reconcile-or-BLOCK: a GL that ties internally but whose total ≠ the master concept's value BLOCKS
    (reconciliation overrides any internal pass) — never a silent tie."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention
    fx, leaves, confirmed = _ppe_fixture()
    store, ms, tb = _ppe_master(6000)                              # concept value 6000 ≠ GL NBV 6650
    note, anchor, _ = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                      sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert anchor.gap == 650.0 and anchor.status() == "BLOCKED"
    assert note.reconciles_to_tb is False and note.tie_ok is False                 # BLOCK, not a forced tie


def test_ppe_internal_tie_fail_surfaced():
    """A schedule that does not roll forward to its closing is surfaced (structural tie fail)."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention

    def break_roll(fx):
        fx["leaves"][0]["closing"] = 1300                          # Land: 1000 + 200 != 1300
    fx, leaves, confirmed = _ppe_fixture(break_roll)
    store, ms, tb = _ppe_master(fx["concept_value"])
    note, _, _ = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                 sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert note.internal_structural_ties_ok is False and note.tie_ok is False


def test_ppe_sign_flip_blocks_independent_of_anchor():
    """The load-bearing add: a depreciation account stored POSITIVE BLOCKS via the explicit sign
    assertion — EVEN when the anchor is fooled into reconciling (concept value set to the wrong total)."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention

    def flip(fx):                                                  # Plant accumulated depreciation → positive
        fx["leaves"][4].update({"opening": 1200, "closing": 1450, "movement_by_ref": {"DEP-CHG": 250}})
    fx, leaves, confirmed = _ppe_fixture(flip)
    store, ms, tb = _ppe_master(9550)                             # the WRONG (overstated) total → anchor reconciles
    note, anchor, sign = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                         sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert anchor.status() == "BUILT"                              # the anchor is fooled...
    assert sign and any("sign disagrees" in s for s in sign)       # ...but the SIGN assertion BLOCKS anyway


def test_ppe_sign_not_recorded_flagged():
    """No recorded convention → flagged magnitude-unverified-on-sign, never assumed."""
    from ai_accountant.master_fs import attach_ppe_note
    fx, leaves, confirmed = _ppe_fixture()
    store, ms, tb = _ppe_master(fx["concept_value"])
    _, _, sign = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed, sign_convention=None)
    assert sign and "not recorded" in sign[0]


def test_load_fails_loud_on_bad_note():
    """A seed note whose concept/anchor is absent or not a leaf, or an unknown mechanism, BLOCKS at load."""
    base = json.loads(SEED_JSON.read_text(encoding="utf-8"))

    def _msg(mutate):
        d = json.loads(json.dumps(base)); mutate(d["engine"])
        p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(d), encoding="utf-8")
        try:
            load_master_store(str(p)); return ""
        except ValueError as e:
            return str(e)
        finally:
            p.unlink()
    assert "not a concept" in _msg(lambda e: e.__setitem__("notes", [{"concept": "NOPE", "mechanism": "roll_forward", "anchor": "NOPE"}]))
    assert "must be a leaf" in _msg(lambda e: e.__setitem__("notes", [{"concept": "bs_total_assets", "mechanism": "roll_forward", "anchor": "bs_total_assets"}]))
    assert "mechanism" in _msg(lambda e: e.__setitem__("notes", [{"concept": "bs_ppe", "mechanism": "telepathy", "anchor": "bs_ppe"}]))
    # Slice N1 optional movement-note vocab is type-checked, never inferred
    assert "caption" in _msg(lambda e: e.__setitem__("notes", [{"concept": "bs_ppe", "mechanism": "roll_forward", "anchor": "bs_ppe", "caption": 123}]))
    assert "exempt_classes" in _msg(lambda e: e.__setitem__("notes", [{"concept": "bs_ppe", "mechanism": "roll_forward", "anchor": "bs_ppe", "exempt_classes": "land"}]))


# ---- Slice N0.1: real per-leaf attribution within ONE concept ------------------------------------
def _ppe_multileaf(add_motor=False, perturb_p1=None):
    from ai_accountant.master_fs.notelib.propose import ConfirmedPPEAccount
    fx = json.loads((ROOT / "tests" / "fixtures" / "regression" / "ppe_synthetic_gl_multileaf.json").read_text(encoding="utf-8"))
    gl, conf, attrib, cleaves = list(fx["gl_leaves"]), dict(fx["confirmed"]), dict(fx["attribution"]), dict(fx["concept_leaves"])
    if add_motor:
        mv = fx["motor_vehicles"]
        gl.append(mv["gl_leaf"]); conf[mv["gl_leaf"]["gl_account"]] = mv["confirmed"]
        attrib[mv["attribution_class"]] = mv["attribution_leaf"]
    if perturb_p1 is not None:
        cleaves["P1"] = perturb_p1
    leaves = [_Leaf(d["gl_account"], d["opening"], d["closing"], dict(d["movement_by_ref"])) for d in gl]
    confirmed = {a: ConfirmedPPEAccount(c, r, "seed", TS) for a, (c, r) in conf.items()}
    store = load_master_store()
    ms = ClientMappingStore()
    for a in cleaves:
        ms.put("demo", MappingRecord(account=a, concept_id="bs_ppe", client_label=a,
                                     provenance="preparer", master_id=store.master_id))
    return store, ms, {a: float(v) for a, v in cleaves.items()}, leaves, confirmed, attrib, cleaves


def test_ppe_multileaf_partial_uncovered_surfaces_loud():
    """Real per-leaf attribution: P1+P2 are covered & reconcile; P3 is UNCOVERED (excluded from BOTH
    sides — never sweeps into the aggregate). PARTIAL must be as LOUD as BLOCK: the coverage finding
    reaches MfsExport.findings, not_final is True, and the note status is queryable as PARTIAL."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    store, ms, tb, leaves, confirmed, attrib, cleaves = _ppe_multileaf()
    note, anchor, _ = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                      attribution=attrib, sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert anchor.gap == 0.0 and anchor.status() == "PARTIAL"          # covered subtotal reconciles
    assert [l.code for l in anchor.uncovered_leaves] == ["P3"]         # the uncovered leaf surfaces
    stored = {"client": "demo",
              "tb": [{"account": a, "label": a, "current": v, "prior": None} for a, v in cleaves.items()],
              "mappings": [{"account": a, "concept_id": "bs_ppe", "client_label": a, "provenance": "preparer",
                            "confidence": "", "flagged_reason": ""} for a in cleaves]}
    m = build_master_fs_export(store, stored, bank="aljazira",
                               note_results={"bs_ppe": {"anchor": anchor, "sign_findings": []}})
    assert any(str(f[0]).startswith("note:bs_ppe") and "P3" in f[2] for f in m.findings)   # (a) finding present
    assert m.not_final is True                                                             # (b) not_final
    assert m.note_status["bs_ppe"] == "PARTIAL" and m.notes_complete is False              # (c) queryable PARTIAL


def test_ppe_multileaf_full_coverage_built():
    """Adding the motor-vehicles class covers P3 → fully covered → BUILT (no spurious PARTIAL)."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention
    store, ms, tb, leaves, confirmed, attrib, _ = _ppe_multileaf(add_motor=True)
    _, anchor, _ = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                   attribution=attrib, sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert anchor.status() == "BUILT" and not anchor.uncovered_leaves


def test_ppe_multileaf_covered_gap_blocks():
    """A covered leaf whose value disagrees with the GL → the covered subtotal does not reconcile → BLOCKED
    (distinct from PARTIAL: a real disagreement, not just missing coverage)."""
    from ai_accountant.master_fs import attach_ppe_note, record_sign_convention
    store, ms, tb, leaves, confirmed, attrib, _ = _ppe_multileaf(perturb_p1=4500)   # P1 4500 ≠ GL 4600
    _, anchor, _ = attach_ppe_note(store, ms, "demo", tb, "bs_ppe", leaves, confirmed,
                                   attribution=attrib, sign_convention=record_sign_convention("demo", approver="r", at=TS))
    assert anchor.status() == "BLOCKED" and anchor.gap == 100.0      # covered subtotal 6550 vs GL 6650


# ---- Slice N0.2: one note total -> N concepts (current/non-current maturity split) ---------------
def _lease_split():
    store = load_master_store(seed_id="telecom_mobily")
    note = next(n for n in store.notes() if n.get("note") == "lease_liabilities")
    fx = json.loads((ROOT / "tests" / "fixtures" / "regression" / "telecom_mobily_published_fixture.json").read_text(encoding="utf-8"))
    nc = float(fx["leaves"]["2024"]["tc_lease_liab_nc"]); c = float(fx["leaves"]["2024"]["tc_lease_liab_c"])
    return store, note, nc, c


def _split_ms(store, populate_both=True, nc=0.0, c=0.0):
    ms = ClientMappingStore()
    ms.put("d", MappingRecord(account="A_nc", concept_id="tc_lease_liab_nc", client_label="x",
                              provenance="preparer", master_id=store.master_id))
    tb = {"A_nc": nc + (0.0 if populate_both else c)}
    if populate_both:
        ms.put("d", MappingRecord(account="A_c", concept_id="tc_lease_liab_c", client_label="x",
                                  provenance="preparer", master_id=store.master_id))
        tb["A_c"] = c
    return ms, tb


def test_split_case_a_reconciles_and_blocks_on_tb_disagreement():
    """Case A (TB carries both halves): the AI classification must AGREE with the TB's independent
    current/non-current values — Σ-check + per-concept match → RECONCILED; disagreement → BLOCKED."""
    from ai_accountant.master_fs import attach_split_note, record_maturity_split, confirm_split
    store, note, nc, c = _lease_split()
    ms, tb = _split_ms(store, True, nc, c)
    lines = {"F1": nc, "F2": c}                                # GL facilities (code has amounts; model never)
    rec = record_maturity_split("d", "lease_liabilities", {"F1": "non_current", "F2": "current"}, approver="r", at=TS)
    assert attach_split_note(store, ms, "d", tb, note, nc + c, lines, rec)["status"] == "SPLIT_UNCONFIRMED"  # firewall
    ok = attach_split_note(store, ms, "d", tb, note, nc + c, lines, confirm_split(rec, approver="r", at=TS))
    assert ok["status"] == "RECONCILED" and ok["portions"]["tc_lease_liab_c"] == c
    bad = attach_split_note(store, ms, "d", tb, note, nc + c, {"F1": nc + 1000, "F2": c - 1000},
                            confirm_split(rec, approver="r", at=TS))
    assert bad["status"] == "BLOCKED" and "disagrees with the TB" in bad["findings"][0][2]


def test_split_case_b_judgment_confirmed_marker_persists_on_export():
    """Case B (TB-combined): the split is judgment-only — JUDGMENT_UNCONFIRMED → (confirm) JUDGMENT_CONFIRMED,
    NEVER RECONCILED. After confirm, not_final clears but the management-judgment marker PERSISTS on the
    rendered line (visible on the statement surface, not just a code query)."""
    from ai_accountant.master_fs import attach_split_note, record_maturity_split, confirm_split
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    store, note, nc, c = _lease_split()
    ms, tb = _split_ms(store, populate_both=False, nc=nc, c=c)   # combined on tc_lease_liab_nc only
    lines = {"F": nc + c}
    rec = record_maturity_split("d", "lease_liabilities", {"F": "non_current"}, approver="r", at=TS)
    assert attach_split_note(store, ms, "d", tb, note, nc + c, lines, rec)["status"] == "JUDGMENT_UNCONFIRMED"
    res = attach_split_note(store, ms, "d", tb, note, nc + c, lines, confirm_split(rec, approver="r", at=TS))
    assert res["status"] == "JUDGMENT_CONFIRMED" and res["judgment_marker"]      # confirmed, still judgment-only
    stored = {"client": "d", "tb": [{"account": "A_nc", "label": "Lease liabilities", "current": nc + c, "prior": None}],
              "mappings": [{"account": "A_nc", "concept_id": "tc_lease_liab_nc", "client_label": "Lease liabilities",
                            "provenance": "preparer", "confidence": "", "flagged_reason": ""}]}
    m = build_master_fs_export(store, stored, bank=None, note_results={"lease_liabilities": {"split": res}})
    assert m.note_status["lease_liabilities"] == "JUDGMENT_CONFIRMED"            # (c) queryable, not RECONCILED
    assert "tc_lease_liab_nc" in m.judgment_markers                             # persistent marker present
    line = next(l for l in m.statements["balance_sheet"] if l.concept_id == "tc_lease_liab_nc")
    assert line.judgment_only is True                                          # marker ON the rendered line


def test_split_unsure_blocks_no_guess():
    """A movement line the classification leaves unsure → BLOCK, no split (no 50/50, no proportional)."""
    from ai_accountant.master_fs import attach_split_note
    store, note, nc, c = _lease_split()
    ms, tb = _split_ms(store, True, nc, c)
    res = attach_split_note(store, ms, "d", tb, note, nc + c, {"F1": nc, "F2": c},
                            {"classification": {"F1": "non_current"}, "provenance": "ai_confirmed"})  # F2 unsure
    assert res["status"] == "BLOCKED" and "no split" in res["findings"][0][2]


def test_split_unconfirmed_firewall_drives_not_final():
    """The firewall is in the ENGINE: an ai_assumed split emits a finding → not_final; confirming removes it."""
    from ai_accountant.master_fs import attach_split_note, record_maturity_split, confirm_split
    from ai_accountant.reporting.master_fs_export import build_master_fs_export
    store, note, nc, c = _lease_split()
    ms, tb = _split_ms(store, True, nc, c)
    lines = {"F1": nc, "F2": c}; cls = {"F1": "non_current", "F2": "current"}
    rec = record_maturity_split("d", "lease_liabilities", cls, approver="r", at=TS)
    stored = {"client": "d", "tb": [{"account": "A_nc", "label": "nc", "current": nc, "prior": None},
                                    {"account": "A_c", "label": "c", "current": c, "prior": None}],
              "mappings": [{"account": "A_nc", "concept_id": "tc_lease_liab_nc", "client_label": "nc", "provenance": "preparer", "confidence": "", "flagged_reason": ""},
                           {"account": "A_c", "concept_id": "tc_lease_liab_c", "client_label": "c", "provenance": "preparer", "confidence": "", "flagged_reason": ""}]}
    un = attach_split_note(store, ms, "d", tb, note, nc + c, lines, rec)
    co = attach_split_note(store, ms, "d", tb, note, nc + c, lines, confirm_split(rec, approver="r", at=TS))
    m_un = build_master_fs_export(store, stored, bank=None, note_results={"lease_liabilities": {"split": un}})
    m_co = build_master_fs_export(store, stored, bank=None, note_results={"lease_liabilities": {"split": co}})
    assert any(str(f[0]) == "split:lease_liabilities" for f in m_un.findings)   # unconfirmed → split finding
    assert not any(str(f[0]) == "split:lease_liabilities" for f in m_co.findings)  # confirmed → cleared


def test_propose_maturity_split_unsure_on_no_signal():
    """Labels-only proposer: a label with no maturity signal returns 'unsure' (never a manufactured split)."""
    from ai_accountant.master_fs import propose_maturity_split
    class _Fake:
        def complete_json(self, prompt, system=None, max_retries=3):
            assert "amount" not in prompt.lower() or "no amounts" in prompt.lower()
            return {"proposals": [{"code": "F1", "maturity": "unsure", "confidence": "low", "evidence": "no maturity in label"}]}
    props = propose_maturity_split([("F1", "Lease liabilities")], client=_Fake())
    assert props[0].maturity == "unsure" and not props[0].is_confident


def test_load_fails_loud_on_bad_split_note():
    base = json.loads((ROOT / "seeds" / "master_fs_telecom_seed.json").read_text(encoding="utf-8"))

    def _msg(mutate):
        d = json.loads(json.dumps(base)); mutate(d["engine"])
        p = Path(tempfile.mktemp(suffix=".json")); p.write_text(json.dumps(d), encoding="utf-8")
        try:
            load_master_store(str(p)); return ""
        except ValueError as e:
            return str(e)
        finally:
            p.unlink()
    assert "split concept" in _msg(lambda e: e["notes"].append({"note": "x", "mechanism": "roll_forward", "splits": [{"concept": "NOPE", "maturity": "current"}, {"concept": "tc_cash", "maturity": "non_current"}]}))
    assert "maturity" in _msg(lambda e: e["notes"].append({"note": "x", "mechanism": "roll_forward", "splits": [{"concept": "tc_cash", "maturity": "someday"}, {"concept": "tc_murabaha", "maturity": "current"}]}))


# ---- Slice N1: the GENERIC movement builder, proven on intangibles (telecom, amortization contra) -----
def _intangibles_fixture(mutate=None):
    fx = json.loads((ROOT / "tests" / "fixtures" / "regression" / "intangibles_synthetic_gl.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(fx)
    from ai_accountant.master_fs.notelib.propose import ConfirmedPPEAccount
    leaves = [_Leaf(d["gl_account"], d["opening"], d["closing"], dict(d["movement_by_ref"])) for d in fx["leaves"]]
    confirmed = {a: ConfirmedPPEAccount(c, r, "seed", TS) for a, (c, r) in fx["confirmed"].items()}
    return fx, leaves, confirmed


def _intangibles_master(concept_value):
    store = load_master_store(seed_id="telecom_mobily")            # telecom seed declares the tc_intangibles note
    note_decl = next(n for n in store.notes() if n.get("concept") == "tc_intangibles")
    ms = ClientMappingStore()
    ms.put("demo", MappingRecord(account="7777", concept_id="tc_intangibles", client_label="Intangibles",
                                 provenance="preparer", master_id=store.master_id))
    return store, ms, {"7777": float(concept_value)}, note_decl


def _attach_intangibles(store, ms, tb, leaves, confirmed, note_decl, sign_convention):
    from ai_accountant.master_fs import attach_movement_note
    from ai_accountant.master_fs.notelib.reference_codes import (INTANGIBLE_COST_CONFIG,
                                                                 INTANGIBLE_AMORT_CONFIG)
    return attach_movement_note(
        store, ms, "demo", tb, "tc_intangibles", leaves, confirmed,
        caption=note_decl["caption"], exempt_classes=set(note_decl.get("exempt_classes", [])),
        cost_config=INTANGIBLE_COST_CONFIG, contra_config=INTANGIBLE_AMORT_CONFIG,
        sign_convention=sign_convention)


def test_intangibles_built_captioned_and_goodwill_exempt():
    """The generic builder on a SECOND single-leaf note: cost + accumulated AMORTIZATION → NBV, reconciles
    to tc_intangibles, captioned 'Intangible assets' (NOT PP&E), and Goodwill is exempt (no missing_contra)."""
    fx, leaves, confirmed = _intangibles_fixture()
    store, ms, tb, decl = _intangibles_master(fx["concept_value"])
    note, anchor, sign = _attach_intangibles(store, ms, tb, leaves, confirmed, decl,
                                             record_sign_convention("demo", approver="r", at=TS))
    assert note.note_ref == "Intangible assets"                                  # captioned, not PP&E
    assert note.total_nbv == fx["expected"]["total_nbv"] and note.nbv_by_class == fx["expected"]["by_class"]
    assert anchor.gap == 0.0 and anchor.status() == "BUILT" and note.tie_ok       # reconciles to the concept
    gw = next(s for s in note.sections if s.asset_class == "Goodwill")
    assert gw.is_exempt and gw.has_contra is False and not gw.missing_contra      # goodwill: cost-only, exempt
    assert gw.nbv == gw.cost == 1500
    assert sign == []                                                             # amortization contra-negative
    # no PP&E vocabulary leaked into the generic note's reasons
    assert not any("depreciation" in r.lower() or "land" in r.lower() for r in note.provisional_reasons())


def test_intangibles_blocks_when_not_reconciling_to_concept():
    """Reconcile-or-BLOCK on the generic note: GL ties internally but total ≠ the concept value → BLOCK."""
    fx, leaves, confirmed = _intangibles_fixture()
    store, ms, tb, decl = _intangibles_master(5000)                              # 5000 ≠ GL NBV 5800
    note, anchor, _ = _attach_intangibles(store, ms, tb, leaves, confirmed, decl,
                                          record_sign_convention("demo", approver="r", at=TS))
    assert anchor.gap == 800.0 and anchor.status() == "BLOCKED"
    assert note.reconciles_to_tb is False and note.tie_ok is False


def test_intangibles_internal_tie_break_surfaced():
    """A cost schedule that does not roll forward to its closing is surfaced (structural tie fail)."""
    def break_roll(fx):
        fx["leaves"][0]["closing"] = 5300                                        # Software cost: 4000 + 1000 != 5300
    fx, leaves, confirmed = _intangibles_fixture(break_roll)
    store, ms, tb, decl = _intangibles_master(fx["concept_value"])
    note, _, _ = _attach_intangibles(store, ms, tb, leaves, confirmed, decl,
                                     record_sign_convention("demo", approver="r", at=TS))
    assert note.internal_structural_ties_ok is False and note.tie_ok is False


def test_intangibles_amortization_sign_flip_blocks():
    """The generic sign assertion: accumulated amortization stored POSITIVE BLOCKS via the explicit
    mechanism-level (contra_closing) sign check — even if the anchor is fooled into reconciling."""
    def flip(fx):                                                                # Licences amortization → positive
        fx["leaves"][3].update({"opening": 800, "closing": 900, "movement_by_ref": {"AMORT-CHG": 100}})
    fx, leaves, confirmed = _intangibles_fixture(flip)
    store, ms, tb, decl = _intangibles_master(7600)                              # the WRONG total → anchor reconciles
    note, anchor, sign = _attach_intangibles(store, ms, tb, leaves, confirmed, decl,
                                             record_sign_convention("demo", approver="r", at=TS))
    assert anchor.status() == "BUILT"                                            # the anchor is fooled...
    assert sign and any("sign disagrees" in s for s in sign)                     # ...but the SIGN assertion BLOCKS


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
                failures += 1
                print(f"[ERROR] {name}: {exc}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
