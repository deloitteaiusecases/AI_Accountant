"""Collect tables from many uploaded sources into one normalized list.

Handles the real-world mess: multiple files, CSV *and* Excel, multi-sheet workbooks, multiple
stacked/adjacent tables per sheet, and foreign column names. Every detected table is tagged with
its source file + sheet, has its columns normalized to canonical names, and is given a level
(banner or inferred) — so downstream routing/compute treat them uniformly regardless of split.

Pipeline per source: detect tables -> tag origin -> normalize columns -> detect level.
"""
from __future__ import annotations

from typing import Any

from ai_accountant.ingestion.normalize import normalize_tables
from ai_accountant.ingestion.table_detect import (
    DetectedTable,
    apply_level_detection,
    detect_tables,
    read_rows_from_filelike,
    read_rows_from_path,
    read_sheets_from_excel,
)


def _tag(tables: list[DetectedTable], source_file: str, sheet: str | None) -> list[DetectedTable]:
    for t in tables:
        t.source_file = source_file
        t.sheet = sheet
    return tables


def _finalize(tables: list[DetectedTable]) -> list[DetectedTable]:
    """Normalize columns then detect levels (level detection relies on canonical names)."""
    return apply_level_detection(normalize_tables(tables))


def collect_from_filelike(file: Any) -> list[DetectedTable]:
    """Detect every table in one uploaded file (CSV or XLSX, all sheets)."""
    name = getattr(file, "name", "uploaded")
    tables: list[DetectedTable] = []
    if name.lower().endswith((".xls", ".xlsx")):
        for sheet_name, rows in read_sheets_from_excel(file).items():
            tables.extend(_tag(detect_tables(rows), name, sheet_name))
    else:  # treat anything else as CSV/text
        tables.extend(_tag(detect_tables(read_rows_from_filelike(file)), name, None))
    return _finalize(tables)


def collect_from_files(files: list[Any]) -> list[DetectedTable]:
    """Detect tables across many uploaded files and return the combined, normalized list."""
    all_tables: list[DetectedTable] = []
    for f in files or []:
        all_tables.extend(collect_from_filelike(f))
    return all_tables


def collect_from_path(path: str) -> list[DetectedTable]:
    """Detect tables from a CSV on disk (used for the bundled sample)."""
    name = path.replace("\\", "/").split("/")[-1]
    return _finalize(_tag(detect_tables(read_rows_from_path(path)), name, None))
