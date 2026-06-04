"""Regression tests for the Note 5 cascade on the bundled sample.

Runnable without pytest:  python tests/test_cascade.py
(also pytest-compatible if pytest is installed).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402


def _result():
    return run_note5_from_path(str(SAMPLE_NOTE5_CSV))


def test_table_detection_counts():
    counts = _result().table_counts()
    assert counts == {"L1": 4, "L2": 5, "L3": 1, "L4": 7, "XREF": 1}, counts


def test_fvtpl_ties_exactly():
    res = _result()
    assert res.cascade.l1["FVTPL"] == 2_780_000


def test_known_variances_are_surfaced():
    res = _result()
    by_item = {line.item: line for line in res.reconciliation}
    assert by_item["FVTPL"].status == "MATCH"
    assert by_item["FVOCI"].variance == 100_000
    assert by_item["Amortised Cost"].variance == -59_500
    assert by_item["TOTAL"].variance == 40_500
    assert res.reconciled is False  # variances exist by design in the sample


def test_l4_is_consumed():
    s = _result().cascade.l4_summary
    assert s.get("purchases_total", 0) > 0
    assert s.get("sales_total", 0) > 0
    assert s.get("income_net_total", 0) > 0


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
