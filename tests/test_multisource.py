"""Phase 2 tests: multi-sheet Excel + multi-file ingestion produce the same result as the
single bundled CSV. Proves the cascade is source-agnostic (any level, any split).

    python tests/test_multisource.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import detect_tables, read_rows_from_path  # noqa: E402


class _Upload:
    """Stand-in for a Streamlit UploadedFile (a named BytesIO; delegates IO to the buffer)."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):  # delegate read/seek/tell/readable/... to the buffer
        return getattr(self.__dict__["_buf"], item)


def _sections() -> dict[str, list[list[str]]]:
    """Split the sample's rows into per-level groups using the banners."""
    rows = read_rows_from_path(str(SAMPLE_NOTE5_CSV))
    groups: dict[str, list[list[str]]] = {}
    current = "header"
    for r in rows:
        text = (r[0] if r else "").upper()
        if "==========" in text:
            if "L1" in text: current = "L1"
            elif "L2" in text: current = "L2"
            elif "L3" in text: current = "L3"
            elif "L4" in text: current = "L4"
            elif "CROSS-REFERENCE" in text: current = "XREF"
        groups.setdefault(current, []).append(r)
    return groups


def _excel_with_sheets(groups: dict[str, list[list[str]]]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for level, rows in groups.items():
            if level in ("L3", "L4"):  # the levels the cascade needs
                pd.DataFrame(rows).to_excel(xw, sheet_name=level, header=False, index=False)
    return buf.getvalue()


def test_excel_multisheet_matches_csv():
    baseline = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    xlsx = _Upload("workbook.xlsx", _excel_with_sheets(_sections()))
    res = run_note5_from_files([xlsx])
    # L3 present in a sheet -> exact (non-partial) path, same headline as the CSV.
    assert res.cascade.partial is False
    assert res.cascade.l1["FVTPL"] == baseline.cascade.l1["FVTPL"] == 2_780_000
    assert res.cascade.l1["TOTAL"] == baseline.cascade.l1["TOTAL"]


def test_l3_split_across_two_files():
    """Split the L3 holdings across two CSV files; totals must still tie out."""
    groups = _sections()
    l3_rows = groups["L3"]
    header_idx = next(i for i, r in enumerate(l3_rows) if r and r[0] == "Holding_ID")
    head, body = l3_rows[: header_idx + 1], l3_rows[header_idx + 1:]
    half = len(body) // 2

    def to_csv(rows):
        out = io.StringIO()
        import csv
        csv.writer(out).writerows(rows)
        return out.getvalue().encode("utf-8")

    f1 = _Upload("l3_part1.csv", to_csv(head + body[:half]))
    f2 = _Upload("l3_part2.csv", to_csv(head + body[half:]))
    res = run_note5_from_files([f1, f2])
    baseline = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    assert res.cascade.l1["TOTAL"] == baseline.cascade.l1["TOTAL"]


def test_level_detection_without_banners():
    """A bannerless L3 sheet should still be tagged L3 by signature."""
    groups = _sections()
    l3_rows = [r for r in groups["L3"] if "==========" not in (r[0] if r else "").upper()]
    tables = detect_tables(l3_rows)
    from ai_accountant.ingestion.table_detect import apply_level_detection
    apply_level_detection(tables)
    assert any(t.level == "L3" for t in tables)


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
