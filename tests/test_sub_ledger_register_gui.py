"""Slice SL-1c.1-gui: the U-register gate — discover which sheets are the registers (propose → confirm), feed
them to the build, show the enriched notes. The engine is done (SL-1c.1/c.2); this tests the GUI WIRING via its
testable helpers (`propose_register_sheets`) + the feed path (the gate's payloads → `build_master_fs_export`).

Proves: discovery (real file → correct sheets at Layer 0, no model); the Layer-1 AI fallback on a differently-
named sheet (no-literal proof, not dead); the headers-only firewall (no attribute VALUE reaches a model); the
feed → ENRICHED notes render with attribute columns; and graceful '(none)' → the coarse TB note.

    python tests/test_sub_ledger_register_gui.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fsgen_mfs                                                              # noqa: E402
from ai_accountant.tb_ingest.register import read_register                    # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                    # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "Draft Data for working.xlsx"


def _headers_of(path):
    from ai_accountant.tb_ingest.grid import load_grid
    from ai_accountant.tb_ingest.parse import detect_header_row

    def _h(sh):
        g = load_grid(str(path), sheet=sh)
        return g[detect_header_row(g)]
    return _h


# ============================================================ discovery — real file, Layer 0 (no model)
def test_discovery_proposes_the_right_sheets_at_layer0():
    if not REAL.exists():
        print("[skip]"); return
    from ai_accountant.tb_ingest.grid import sheet_names
    store = load_master_store(seed_id="ksa_bank")
    prop = fsgen_mfs.propose_register_sheets(store, sheet_names(str(REAL)), "Trial Balance",
                                             _headers_of(REAL), client=None)   # NO client → must be Layer 0
    assert prop["bs_investments"]["sheet"] == "Investment " and prop["bs_investments"]["layer"] == 0
    assert prop["bs_loans"]["sheet"] == "Financing -net" and prop["bs_loans"]["layer"] == 0


def test_only_register_declaring_concepts_are_offered_a_sheet():
    store = load_master_store(seed_id="ksa_bank")
    decls = dict(fsgen_mfs.register_decls(store))
    assert set(decls) == {"bs_investments", "bs_loans"}                       # NOT every concept; the 13 other sheets untouched


# ============================================================ Layer-1 AI fallback (no-literal proof, not dead)
def test_layer1_ai_fires_on_a_differently_named_register_sheet():
    seen = {}

    class _Fake:
        def complete_json(self, prompt, system=None, max_retries=3):
            seen["prompt"] = prompt
            return {"concept_id": "bs_investments", "evidence": "securities headers"}
    store = load_master_store(seed_id="ksa_bank")
    # a sheet whose NAME doesn't match any concept → Layer 0 miss → Layer 1 AI
    headers = {"Annex 7": ["Security ID", "Classification", "Carrying Value 2025"], "Trial Balance": ["x"]}
    prop = fsgen_mfs.propose_register_sheets(store, ["Trial Balance", "Annex 7"], "Trial Balance",
                                             lambda sh: headers[sh], client=_Fake())
    assert prop["bs_investments"]["sheet"] == "Annex 7" and prop["bs_investments"]["layer"] == 1
    assert "Security ID" in seen["prompt"] and "Carrying" in seen["prompt"]    # headers reached the model …


# ============================================================ headers-only firewall — no VALUE to any model
def test_discovery_sends_headers_only_never_a_row_value():
    if not REAL.exists():
        print("[skip]"); return
    captured = []

    class _Capture:
        def complete_json(self, prompt, system=None, max_retries=3):
            captured.append(prompt)
            return {"concept_id": "unsure", "evidence": ""}
    from ai_accountant.tb_ingest.grid import sheet_names
    store = load_master_store(seed_id="ksa_bank")
    # force Layer 1 for every sheet by passing a TB name that matches nothing, so the AI is consulted
    fsgen_mfs.propose_register_sheets(store, sheet_names(str(REAL)), "Trial Balance", _headers_of(REAL),
                                      client=_Capture())
    blob = " ".join(captured)
    reg = read_register(__import__("ai_accountant.tb_ingest.grid", fromlist=["load_grid"]).load_grid(
        str(REAL), sheet="Investment "))
    for r in reg["rows"][:15]:                                                # NO attribute value may appear in any prompt
        for v in r["cells"]:
            if str(v).strip() and len(str(v)) > 4 and not any(str(v) in h for h in reg["columns"]):
                assert str(v) not in blob, f"attribute value {v!r} leaked to the model"


# ============================================================ feed → ENRICHED notes render (the milestone)
def test_feed_builds_both_enriched_register_notes():
    if not REAL.exists():
        print("[skip]"); return
    from ai_accountant.tb_ingest.grid import load_grid
    store = load_master_store(seed_id="ksa_bank")
    # the gate's payloads: read each confirmed register sheet
    payloads = {"bs_investments": read_register(load_grid(str(REAL), sheet="Investment ")),
                "bs_loans": read_register(load_grid(str(REAL), sheet="Financing -net"))}
    tb = ([{"account": "I1", "label": "Held at FVIS", "current": 38967880.0, "prior": 36406356.0, "section": "Assets",
            "maturity_hint": "", "levels": ["Assets", "", "Investments, net", "Held at FVIS", ""]},
           {"account": "L1", "label": "Commercial Financing", "current": 110862169.0, "prior": 96912496.0,
            "section": "Assets", "maturity_hint": "", "levels": ["Assets", "", "Financing, net", "Commercial Financing", ""]}])
    maps = [{"account": "I1", "concept_id": "bs_investments", "client_label": "x", "provenance": "preparer"},
            {"account": "L1", "concept_id": "bs_loans", "client_label": "x", "provenance": "preparer"}]
    m = build_master_fs_export(store, {"client": "d", "master_id": store.master_id, "tb": tb, "mappings": maps,
                                       "extensions": []}, gl=payloads, notes_attempted=True)
    enriched = [v for v in m.note_views if v.columns]                        # register-table note views
    assert len(enriched) == 2                                                # BOTH enriched notes built + render
    assert any("Credit Rating" in c for v in enriched for c in v.columns)    # Investment's attributes
    assert any("Segment" in c for v in enriched for c in v.columns)          # Financing's attributes


# ============================================================ graceful — '(none)' keeps the coarse note
def test_none_keeps_the_coarse_tb_note():
    store = load_master_store(seed_id="ksa_bank")
    tb = [{"account": "I1", "label": "Held at FVIS", "current": 38967880.0, "prior": 36406356.0, "section": "Assets",
           "maturity_hint": "", "levels": ["Assets", "", "Investments, net", "Held at FVIS", ""]}]
    maps = [{"account": "I1", "concept_id": "bs_investments", "client_label": "x", "provenance": "preparer"}]
    m = build_master_fs_export(store, {"client": "d", "master_id": store.master_id, "tb": tb, "mappings": maps,
                                       "extensions": []}, gl={}, notes_attempted=True)   # no register payload → coarse
    assert "static" in m.note_results["bs_investments"] and "register" not in m.note_results["bs_investments"]


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
