"""Permanent QA scenario tests (promoted from scripts/qa_suite.py).

Covers cross-scenario behaviors not otherwise pinned: multi-file merge equivalence, streamed
large-file confidence, opening roll-forward control, cross-source control.

    python tests/test_qa_scenarios.py
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import detect_tables, read_rows_from_path  # noqa: E402

TABLES = detect_tables(read_rows_from_path(str(SAMPLE_NOTE5_CSV)))


class U:
    def __init__(self, name, data):
        self.name = name
        self._b = io.BytesIO(data)

    def __getattr__(self, k):
        return getattr(self.__dict__["_b"], k)


def _csv_of(*tables) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    for t in tables:
        if t.title:
            w.writerow([t.title])
        w.writerow(t.headers)
        for rec in t.records:
            w.writerow([rec.get(h, "") for h in t.headers])
        w.writerow([])
    return out.getvalue().encode("utf-8")


def _l4():
    return [t for t in TABLES if t.level == "L4"]


def test_l4_split_across_files_equals_l4_only():
    l4 = _l4()
    single = run_note5_from_files([U("l4.csv", _csv_of(*l4))])
    split = run_note5_from_files([U(f"l4_{i}.csv", _csv_of(t)) for i, t in enumerate(l4)])
    assert split.cascade.l1["TOTAL"] == single.cascade.l1["TOTAL"]
    assert split.cascade.l1["FVTPL"] == single.cascade.l1["FVTPL"]


def test_streamed_large_file_has_confidence():
    classes = ["FVTPL", "FVOCI", "AC"]
    rows = ["Holding_ID,Security_Name,Classification,Carrying_Value_000"]
    rows += [f"H-{i},Security {i},{classes[i % 3]},1000" for i in range(200_000)]
    res = run_note5_from_files([U("big.csv", ("\n".join(rows)).encode("utf-8"))])
    assert "streamed" in res.cascade.l3_source          # took the streaming path
    assert res.confidence.controls                       # controls now run on streamed files
    assert res.confidence.level == "High"                # (was "Unknown" before hardening)


def test_opening_plus_l4_has_rollforward_control():
    op = U("op.csv", b"Classification,Opening_000\nFVTPL,2200000\nFVOCI,10800000\nAC,8500000\n")
    l4 = U("l4.csv", _csv_of(*_l4()))
    res = run_note5_from_files([op, l4])
    assert any("Roll-forward" in c.name for c in res.confidence.controls)


def test_sample_has_cross_source_control():
    res = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    assert any("Cross-source" in c.name for c in res.confidence.controls)


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
