"""Tests for Phase 2 hardening: adjacent-table splitting and foreign-column normalization.

    python tests/test_hardening.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.normalize import canonical_for, normalize_tables  # noqa: E402
from ai_accountant.ingestion.table_detect import detect_tables  # noqa: E402


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):
        return getattr(self.__dict__["_buf"], item)


def test_adjacent_tables_split_without_blank_line():
    """Two tables with different columns, no blank row between them -> two tables."""
    rows = [
        ["Holding_ID", "Classification", "Carrying_Value_000"],
        ["AC-1", "AC", "100"],
        ["AC-2", "AC", "200"],
        ["Txn_ID", "Holding_ID", "Total_Cost_000"],   # new header, no blank line above
        ["PUR-1", "AC-1", "100"],
        ["PUR-2", "AC-2", "200"],
    ]
    tables = detect_tables(rows)
    assert len(tables) == 2, [t.headers for t in tables]
    assert tables[0].has_columns("Carrying_Value_000")
    assert tables[1].has_columns("Total_Cost_000")


def test_canonical_alias_mapping():
    assert canonical_for("Acquisition Cost") == "Total_Cost_000"
    assert canonical_for("Carrying Value") == "Carrying_Value_000"
    assert canonical_for("Asset Class") == "Classification"
    assert canonical_for("Security ID") == "Holding_ID"
    assert canonical_for("Some Random Column") == "Some Random Column"  # untouched


def test_sample_columns_not_clobbered():
    """Normalization must leave the sample's own (non-aliased) columns alone."""
    rows = [["Holding_ID", "ISIN", "Fair_Value_000", "Face_Value_000"], ["AC-1", "X", "1", "2"]]
    t = detect_tables(rows)[0]
    normalize_tables([t])
    assert t.headers == ["Holding_ID", "ISIN", "Fair_Value_000", "Face_Value_000"]


def test_foreign_column_names_still_compute():
    """Rename the sample's headers to foreign aliases; the cascade must still tie out."""
    text = SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig")
    renamed = (text
               .replace("Holding_ID", "Security ID")
               .replace("Carrying_Value_000", "Carrying Value")
               .replace("Classification", "Asset Class")
               .replace("Total_Cost_000", "Acquisition Cost"))
    up = _Upload("foreign.csv", renamed.encode("utf-8"))
    res = run_note5_from_files([up])  # deterministic alias layer, no API key
    baseline = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    assert res.cascade.l1["FVTPL"] == 2_780_000
    assert res.cascade.l1["TOTAL"] == baseline.cascade.l1["TOTAL"]


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
