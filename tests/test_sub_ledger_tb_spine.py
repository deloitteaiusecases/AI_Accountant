"""Slice SL-1: TB-spine note generation — route TB rows to concepts and build every TB-granularity note
on the EXISTING static-breakdown path, degrading to the granularity the TB supports.

Derived from the real `Draft Data for working.xlsx` bank TB (the BS-side note rows, verbatim numbers). Proves:
  * ROUTING with NO Source column — each row resolves to its concept via `resolve_row` (the L2 level alias),
    Source-absent, deterministic (the no-dependency property).
  * BUILD on the existing machinery — `build_master_fs_export(notes_attempted=True)` builds each declared
    static_breakdown note (the seed declarations added in SL-1.A); no new build path.
  * TIE — each note foots to its face concept both years (the partition firewall, notes.py:427-432): no
    BLOCKED finding, the total row == the face value.
  * GRACEFUL DEGRADATION — the note has exactly the TB's L3 lines (Demand/Saving/Time/Other), NOT the gold
    standard's finer sub-types (which have no TB source). Coarser-but-tied is BUILT, never refused/flagged.

    python tests/test_sub_ledger_tb_spine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.seed import load_master_store                 # noqa: E402
from ai_accountant.tb_ingest.resolve import resolve_row                    # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export  # noqa: E402

# Real BS-side rows from the AlJazira TB: concept -> (L2 level, [(gl, L3 label, current, prior)]).
FIXTURE = {
    "bs_deposits": ("Customers' deposits", [
        ("1047", "Demand", -32046487, -34564643),
        ("1048", "Saving and call deposits", -13654158, -11114104),
        ("1049", "Customers' time investments", -67398888, -60193863),
        ("1050", "Other", -2295782, -2313904)]),
    "bs_cash": ("Cash and balances with Saudi Central Bank (SAMA)", [
        ("1000", "Cash in hand", 541422, 688914),
        ("1001", "Wakala placement with SAMA", 494948, 0),
        ("1002", "Other balances", 518153, 465421),
        ("1003", "Statutory deposit with SAMA", 5504686, 5429455)]),
    "bs_other_assets": ("Other assets", [
        ("1034", "Advances, prepayments and other receivables", 430562, 224595),
        ("1035", "Margin deposits against financial instruments", 75760, 2028),
        ("1036", "VAT and tax related receivables", 45845, 77199),
        ("1037", "Others", 374857, 341874)]),
    "bs_due_to": ("Due to banks, Saudi Central Bank and other financial institutions", [
        ("1044", "Current accounts", -340077, -296103),
        ("1045", "Money market deposits", -17932704, -8440523),
        ("1046", "Repurchase agreement borrowings", -5639449, -10572707)]),
    "bs_other_liab": ("Other liabilities", [
        ("1052", "Accounts payable", -882890, -678982),
        ("1053", "Employee benefit obligations", -340436, -309433),
        ("1054", "Lease liability - discounted", -203537, -177821),
        ("1055", "Loss allowance for credit related commitments and contingencies", -323358, -351252),
        ("1056", "Dividend payable", -48282, -62934),
        ("1057", "AlJazira Philanthropic Program", -8989, -4953),
        ("1058", "Others", -845712, -452232)]),
}
_SECTION = {"bs_deposits": "Liability", "bs_due_to": "Liability", "bs_other_liab": "Liability",
            "bs_cash": "Assets", "bs_other_assets": "Assets"}


def _tb_rows():
    rows = []
    for cid, (l2, lines) in FIXTURE.items():
        sec = _SECTION[cid]
        for gl, l3, cur, pri in lines:
            rows.append({"account": gl, "label": l3, "current": float(cur), "prior": float(pri),
                         "section": sec, "maturity_hint": f"{sec} - NC/C",
                         "levels": [sec, f"{sec} - NC/C", l2, l3, ""], "_concept": cid})
    return rows


def _build(store, tb_rows, mappings, *, accepted=None):
    stored = {"client": "draft", "master_id": store.master_id, "tb": tb_rows,
              "mappings": mappings, "extensions": []}
    if accepted is not None:
        stored["breakdowns"] = accepted
    return build_master_fs_export(store, stored, notes_attempted=True)


def _note(m, concept_caption_fragment):
    return next(v for v in m.note_views if concept_caption_fragment in v.note_ref)


# ============================================================ routing — NO Source column (the no-dependency proof)
def test_routing_resolves_every_row_to_its_concept_with_no_source_column():
    store = load_master_store(seed_id="ksa_bank")
    for r in _tb_rows():
        concept, matched = resolve_row(store, r)                  # NO Source consulted — pure resolve_row
        assert concept is not None and concept.concept_id == r["_concept"], \
            f"{r['account']} {r['label']!r} routed to {concept and concept.concept_id} (want {r['_concept']})"


# ============================================================ build + tie + graceful degradation
def test_every_tb_granularity_note_builds_ties_and_degrades_to_tb_lines():
    store = load_master_store(seed_id="ksa_bank")
    tb = _tb_rows()
    maps = [{"account": r["account"], "concept_id": r["_concept"], "client_label": r["label"],
             "provenance": "preparer"} for r in tb]
    m = _build(store, tb, maps)
    for cid, (l2, lines) in FIXTURE.items():
        v = next(v for v in m.note_views if v.note_ref and _caption_of(store, cid) in v.note_ref)
        # BUILT path (foots) — GROUPING_UNCONFIRMED becomes BUILT on accept; NEVER blocked / not-generated
        assert v.status in ("GROUPING_UNCONFIRMED", "BUILT"), f"{cid}: status {v.status}"
        body = [r for r in v.rows if r.kind != "total"]
        total = next(r for r in v.rows if r.kind == "total")
        # GRACEFUL DEGRADATION: exactly the TB's L3 lines, NOT a finer fabricated split
        assert len(body) == len(lines), f"{cid}: {len(body)} lines vs {len(lines)} TB rows (no fabrication)"
        # TIE (both years): the note total == Σ rows == the face value (partition firewall held)
        want_cur = round(sum(c for _g, _l, c, _p in lines), 2)
        want_pri = round(sum(p for _g, _l, _c, p in lines), 2)
        assert abs(total.value - want_cur) < 0.01, f"{cid}: total {total.value} != Σ {want_cur}"
        assert abs(total.prior_value - want_pri) < 0.01, f"{cid}: prior {total.prior_value} != Σ {want_pri}"


def test_no_blocked_finding_on_any_tb_granularity_note():
    store = load_master_store(seed_id="ksa_bank")
    tb = _tb_rows()
    maps = [{"account": r["account"], "concept_id": r["_concept"], "client_label": r["label"],
             "provenance": "preparer"} for r in tb]
    m = _build(store, tb, maps)
    blocked = [f for f in m.findings if "BLOCK" in str(f).upper() and "static" in str(f).lower()]
    assert not blocked, f"unexpected BLOCK findings: {blocked}"


def test_degradation_deposits_is_four_lines_not_the_gold_retail_corporate_split():
    """The gold N13 shows Retail/Corporate sub-tenors (finer than the TB). The engine builds the 4 TB lines
    (Demand/Saving/Time/Other), tied — the coarser-but-correct note, never inventing the absent sub-types."""
    store = load_master_store(seed_id="ksa_bank")
    tb = [r for r in _tb_rows() if r["_concept"] == "bs_deposits"]
    maps = [{"account": r["account"], "concept_id": "bs_deposits", "client_label": r["label"],
             "provenance": "preparer"} for r in tb]
    m = _build(store, tb, maps)
    v = next(v for v in m.note_views if "deposits" in v.note_ref)
    body = [r for r in v.rows if r.kind != "total"]
    labels = {r.label for r in body}
    assert len(body) == 4 and "Demand" in labels
    assert not any("Retail" in l or "Corporate" in l for l in labels)   # never fabricated
    assert v.status != "BLOCKED" and v.rows                              # BUILT/foots, not refused


def _caption_of(store, concept_id):
    for d in store.notes():
        if d.get("concept") == concept_id and d.get("mechanism") == "static_breakdown":
            return d.get("caption", "")
    return ""


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
