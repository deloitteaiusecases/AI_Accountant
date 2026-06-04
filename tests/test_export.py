"""Phase 5 tests: Excel + PDF export of the computed Note 5.

    python tests/test_export.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from ai_accountant.compute.note5 import run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.export import export_to_excel, export_to_pdf  # noqa: E402


def _res():
    return run_note5_from_path(str(SAMPLE_NOTE5_CSV))


def test_excel_opens_and_has_expected_sheets():
    data = export_to_excel(_res())
    assert isinstance(data, bytes) and len(data) > 0
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    for name in ("Note 5 (L1)", "Classification (L2)", "Sub-ledger (L3)",
                 "Reconciliation", "Confidence"):
        assert name in sheets, f"missing sheet: {name} (have {list(sheets)})"


def test_excel_l1_values_match_computed():
    res = _res()
    data = export_to_excel(res)
    l1 = pd.read_excel(io.BytesIO(data), sheet_name="Note 5 (L1)")
    by_line = dict(zip(l1["Line"], l1["Amount (SAR '000)"]))
    assert by_line["FVTPL"] == res.cascade.l1["FVTPL"] == 2_780_000
    assert by_line["TOTAL"] == res.cascade.l1["TOTAL"]


def test_pdf_is_valid():
    data = export_to_pdf(_res())
    assert isinstance(data, bytes) and data[:4] == b"%PDF"
    assert len(data) > 1000  # non-trivial document


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
