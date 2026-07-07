"""Slice I1: the retained-close is detect-and-confirm, never automatic, and cannot double-count.

Drives the real deterministic TB-ingest pipeline on Abhishek's TB_Test (a PRE-CLOSE trial balance) and
asserts: the engine DETECTS pre-close (imbalance == the current-year result); closing balances the SOFP
and ties to the published retained (opening + result), with net profit counted ONCE; a SECOND detect on
the now-closed TB reads post-close (no second close); declining the close on a pre-close TB leaves the
SOFP visibly off by the result (surfaced, never auto-fixed); and apply refuses any non-pre-close verdict.

    python tests/test_tb_close.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.master_fs.close import apply_retained_close, detect_close_state   # noqa: E402
from ai_accountant.master_fs.mapping import apply_mapping_decisions                  # noqa: E402
from ai_accountant.master_fs.model import ClientMappingStore, ProvenanceStore        # noqa: E402
from ai_accountant.master_fs.orchestrator import _stored_from_mapping                # noqa: E402
from ai_accountant.master_fs.seed import load_master_store                           # noqa: E402
from ai_accountant.reporting.master_fs_export import build_master_fs_export          # noqa: E402
from ai_accountant.tb_ingest import (apply_tb_sign, confirm_column_roles, confirm_tb_sign,  # noqa: E402
                                     detect_header_row, load_grid, parse_tb, propose_column_roles,
                                     propose_tb_sign, to_engine_inputs)
from ai_accountant.tb_ingest.resolve import build_upload_proposals                   # noqa: E402

TB = Path(__file__).resolve().parent / "fixtures" / "tb_upload" / "tb_test.xlsx"


def _pre_close_stored():
    """The deterministic TB-ingest path on TB_Test → a PRE-CLOSE stored mapping result (no close yet)."""
    grid = load_grid(str(TB))
    hdr = detect_header_row(grid)
    schema = confirm_column_roles(propose_column_roles(grid[hdr], grid[hdr + 1:hdr + 6], client=None))
    parsed = parse_tb(grid, schema, header_row=hdr)
    _items, tb_rows = to_engine_inputs(parsed)
    tb_rows = apply_tb_sign(tb_rows, confirm_tb_sign(propose_tb_sign(tb_rows), approver="t", at="t"))
    store = load_master_store(seed_id="telecom_mobily")
    props = build_upload_proposals(tb_rows, store, client=None)
    ms, au = ClientMappingStore(), ProvenanceStore()
    apply_mapping_decisions(props, store, client_id="tb", decisions={p.code: "confirm" for p in props},
                            mapping_store=ms, audit=au, approver="t", at="t")
    return store, _stored_from_mapping(ms, "tb", store.master_id, tb_rows)


def _line(model, cid):
    return next((l.current for st in model.statements.values() for l in st if l.concept_id == cid), None)


def test_pre_close_detected_then_closes_to_balance_without_double_count():
    store, stored = _pre_close_stored()
    cp = detect_close_state(store, build_master_fs_export(store, stored))
    assert cp.verdict == "pre_close"
    assert round(cp.imbalance_current) == round(cp.result_total_current) == 3062385    # off by EXACTLY the result
    closed = apply_retained_close(stored, cp, approver="t", at="t")
    m = build_master_fs_export(store, closed)
    assert round(_line(m, "tc_total_assets") - _line(m, "tc_total_oe")) == 0            # balances
    assert round(_line(m, "tc_retained")) == 11198161                                  # opening + result, once
    assert round(_line(m, "tc_net_profit")) == 3106848                                 # net profit NOT doubled
    assert not [f for f in m.findings if str(f[0]) == "balance check"]


def test_closed_tb_then_reads_post_close_no_second_close():
    store, stored = _pre_close_stored()
    cp = detect_close_state(store, build_master_fs_export(store, stored))
    closed = apply_retained_close(stored, cp, approver="t", at="t")
    cp2 = detect_close_state(store, build_master_fs_export(store, closed))
    assert cp2.verdict == "post_close"                                                 # no second close offered


def test_declining_the_close_on_a_pre_close_tb_leaves_it_unbalanced():
    store, stored = _pre_close_stored()
    m = build_master_fs_export(store, stored)                                          # NO close applied
    assert round(_line(m, "tc_total_assets") - _line(m, "tc_total_oe")) == 3062385      # off by the result — surfaced
    assert [f for f in m.findings if str(f[0]) == "balance check"]                      # the engine flags it, never auto-fixes


def test_apply_refuses_a_non_pre_close_verdict():
    store, stored = _pre_close_stored()
    cp = detect_close_state(store, build_master_fs_export(store, stored))
    closed = apply_retained_close(stored, cp, approver="t", at="t")
    post = detect_close_state(store, build_master_fs_export(store, closed))
    try:
        apply_retained_close(closed, post, approver="t", at="t")
        raise AssertionError("apply_retained_close ran on a post_close verdict")
    except ValueError:
        pass


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
