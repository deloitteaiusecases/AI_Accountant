"""Slice SL-1.C: the OPTIONAL `Source` note-routing tag — opaque key, accelerator only, NO dependency.

Proves: the tag is parsed into opaque group keys (compound/sub-section handled); it cross-checks the engine's
concept-resolution and surfaces conflicts (never auto-routes); the column role is recognised; and — the
mandatory no-dependency property — the SAME notes build whether the Source column is present or absent.

    python tests/test_sub_ledger_source.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.tb_ingest.columns import confirm_column_roles, heuristic_column_roles   # noqa: E402
from ai_accountant.tb_ingest.source_route import parse_source_tag, source_routing_audit     # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                                   # noqa: E402
from ai_accountant.tb_ingest.resolve import resolve_row                                      # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export                  # noqa: E402
from tests.test_sub_ledger_tb_spine import FIXTURE, _SECTION                                 # noqa: E402


# ============================================================ tag parsing (opaque, compound, sub-section)
def test_parse_source_tag_compound_and_subsection():
    # keys are OPAQUE + consistent: the "Note " prefix is stripped so "Note 30" and "...,30" share a key
    assert parse_source_tag("Note 13") == ["13"]
    assert parse_source_tag("Note 15, 30") == ["15", "30"]                # compound → two memberships
    assert parse_source_tag("Note 15(a)") == ["15"]                       # sub-section → parent group
    assert parse_source_tag("Note 11.3") == ["11"]                        # dotted sub → parent
    assert parse_source_tag("Note 18, 30.1(d)") == ["18", "30"]
    assert parse_source_tag("Note 30") == parse_source_tag("Note 15, 30")[1:]   # "Note 30" == the "30" key
    assert parse_source_tag("") == [] and parse_source_tag(None) == []    # blank → no membership


# ============================================================ column role recognised
def test_source_column_role_recognised_not_ignored():
    schema = confirm_column_roles(heuristic_column_roles(
        ["GL Number", "2024", "L2", "Source"], [["1", "5", "Cash", "Note 4"]]))
    assert schema.source_index == 3                                       # 'Source' → source_route, not 'ignore'


# ============================================================ cross-check: conflict + split surfaced, never auto-route
def test_audit_flags_conflict_when_one_tag_resolves_to_two_concepts():
    tb = [{"account": "a", "source_tag": "Note 99"}, {"account": "b", "source_tag": "Note 99"}]
    resolved = {"a": "bs_cash", "b": "bs_deposits"}                       # same tag, different concepts
    aud = source_routing_audit(tb, resolved)
    assert aud["has_source"] is True
    assert aud["conflicts"] and aud["conflicts"][0]["concepts"] == ["bs_cash", "bs_deposits"]


def test_audit_no_source_column_is_a_noop():
    tb = [{"account": "a"}, {"account": "b"}]                             # no source_tag → Source absent
    aud = source_routing_audit(tb, {"a": "bs_cash", "b": "bs_deposits"})
    assert aud["has_source"] is False and not aud["conflicts"] and not aud["groups"]


# ============================================================ THE NO-DEPENDENCY PROOF: same notes ± Source
def _build_notes(store, with_source: bool):
    rows, maps = [], []
    src_for = {"bs_deposits": "Note 13", "bs_other_liab": "Note 15", "bs_cash": "Note 4",
               "bs_other_assets": "Note 8", "bs_due_to": "Note 12"}
    for cid, (l2, lines) in FIXTURE.items():
        sec = _SECTION[cid]
        for gl, l3, cur, pri in lines:
            r = {"account": gl, "label": l3, "current": float(cur), "prior": float(pri), "section": sec,
                 "maturity_hint": f"{sec} - NC/C", "levels": [sec, f"{sec} - NC/C", l2, l3, ""]}
            if with_source:
                r["source_tag"] = src_for[cid]
            rows.append(r)
            maps.append({"account": gl, "concept_id": resolve_row(store, r)[0].concept_id,
                         "client_label": l3, "provenance": "preparer"})
    stored = {"client": "draft", "master_id": store.master_id, "tb": rows, "mappings": maps, "extensions": []}
    m = build_master_fs_export(store, stored, notes_attempted=True)
    return {v.note_ref: (v.status, [(r.label, r.value, r.prior_value, r.kind) for r in v.rows])
            for v in m.note_views}


def test_same_notes_built_with_and_without_the_source_column():
    store = load_master_store(seed_id="ksa_bank")
    with_src = _build_notes(store, True)
    without_src = _build_notes(store, False)
    assert with_src == without_src, "Source column changed the built notes — it must be a pure accelerator"


def test_real_source_tags_agree_with_resolution_no_conflicts_on_bs_rows():
    """On the real BS-side rows, the preparer's Source tags and the engine's concept-resolution AGREE — each
    tag groups rows of ONE concept (no conflict). (Proves the cross-check passes clean on real data.)"""
    store = load_master_store(seed_id="ksa_bank")
    tb, resolved = [], {}
    src_for = {"bs_deposits": "Note 13", "bs_other_liab": "Note 15", "bs_cash": "Note 4",
               "bs_other_assets": "Note 8", "bs_due_to": "Note 12"}
    for cid, (l2, lines) in FIXTURE.items():
        sec = _SECTION[cid]
        for gl, l3, cur, pri in lines:
            r = {"account": gl, "label": l3, "section": sec, "maturity_hint": f"{sec} - NC/C",
                 "levels": [sec, f"{sec} - NC/C", l2, l3, ""], "source_tag": src_for[cid]}
            tb.append(r)
            resolved[gl] = resolve_row(store, r)[0].concept_id
    aud = source_routing_audit(tb, resolved)
    assert aud["has_source"] and not aud["conflicts"] and not aud["split"]


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
