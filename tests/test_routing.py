"""Tests for the deterministic value-routing map on the bundled sample.

    python tests/test_routing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.ingestion.collect import collect_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.routing import build_routing_map  # noqa: E402


def _map():
    return build_routing_map(collect_from_path(str(SAMPLE_NOTE5_CSV)))


def test_every_table_routed():
    rm = _map()
    assert len(rm.entries) == 18  # same 18 tables the detector finds


def test_key_roles_identified():
    roles = {e.role for e in _map().entries}
    for expected in {"sub-ledger holdings", "purchases", "sales/maturities",
                     "coupon/dividend income", "mark-to-market revaluation",
                     "EIR amortisation", "classification summary", "cross-reference map"}:
        assert expected in roles, f"missing role: {expected}"


def test_sub_ledger_is_l3_and_used():
    sl = [e for e in _map().entries if e.role == "sub-ledger holdings"]
    assert len(sl) == 1
    assert sl[0].level == "L3"
    assert sl[0].used_in_cascade is True


def test_fs_face_not_used_in_cascade():
    rm = _map()
    bs = [e for e in rm.entries if e.role == "FS face — balance sheet"]
    assert bs and bs[0].used_in_cascade is False  # L1 face is an output, not an input


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
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
