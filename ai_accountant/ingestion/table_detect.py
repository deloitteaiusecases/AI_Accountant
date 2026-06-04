"""Detect multiple stacked tables within a single sheet/file.

A single sheet can hold several tables one after another (the sample CSV stacks L1, L2,
L3, L4 and a cross-reference map), separated by blank rows, section banners
(``========== L3: ... ==========``) and sub-table titles (``5.1 ...``, ``L4-A: ...``).

This Phase 1 implementation targets that layout but is written generically (blank-row
blocking + banner/title peeling) so Phase 2 can extend it to arbitrary workbooks.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_LEVEL_RE = re.compile(r"(L[1-4])\b", re.IGNORECASE)
_BANNER_RE = re.compile(r"={3,}")


@dataclass
class DetectedTable:
    """One table found inside a sheet."""

    level: str | None            # "L1".."L4", "XREF", or None
    title: str | None            # e.g. "5.1 CLASSIFICATION SUMMARY", "L4-A: PURCHASE..."
    headers: list[str]
    records: list[dict[str, Any]] = field(default_factory=list)
    source_file: str | None = None
    sheet: str | None = None

    @property
    def df(self) -> pd.DataFrame:
        return pd.DataFrame(self.records, columns=self.headers)

    def has_columns(self, *cols: str) -> bool:
        hset = {h.strip() for h in self.headers}
        return all(c in hset for c in cols)

    @property
    def origin(self) -> str:
        parts = [p for p in (self.source_file, self.sheet) if p]
        return " · ".join(parts) if parts else "(uploaded)"


# --- low-level row readers ----------------------------------------------------
def read_rows_from_text(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def read_rows_from_path(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def read_rows_from_filelike(file: Any) -> list[list[str]]:
    file.seek(0)
    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    return read_rows_from_text(raw)


def read_sheets_from_excel(file: Any) -> dict[str, list[list[str]]]:
    """Read every sheet of an Excel workbook as raw rows (strings, blanks preserved)."""
    file.seek(0)
    sheets = pd.read_excel(file, sheet_name=None, header=None, dtype=str)
    out: dict[str, list[list[str]]] = {}
    for name, df in sheets.items():
        out[name] = df.fillna("").astype(str).values.tolist()
    return out


# --- level detection (when section banners are absent) ------------------------
# Column signatures that identify a table's level without a banner.
_LEVEL_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("L4", ("Total_Cost_000",)),
    ("L4", ("Proceeds_000",)),
    ("L4", ("MtM_Change_000",)),
    ("L4", ("Monthly_Amort_000",)),
    ("L4", ("Income_Type", "Net_000")),
    ("L4", ("ECL_000",)),
    ("L3", ("Holding_ID", "Carrying_Value_000")),
    ("L2", ("Classification", "Sub-Category")),
    ("L1", ("BS_Line",)),
    ("L1", ("P&L_Line",)),
]


def detect_level(table: DetectedTable) -> str | None:
    """Infer a table's level from its columns; returns None if unknown."""
    for level, cols in _LEVEL_SIGNATURES:
        if table.has_columns(*cols):
            return level
    return None


def apply_level_detection(tables: list[DetectedTable]) -> list[DetectedTable]:
    """Fill in `level` for any table that has none (e.g. files without banners)."""
    for t in tables:
        if t.level is None:
            t.level = detect_level(t)
    return tables


# --- helpers ------------------------------------------------------------------
def _nonempty(row: list[str]) -> list[str]:
    return [c for c in row if str(c).strip() != ""]


def _is_blank(row: list[str]) -> bool:
    return len(_nonempty(row)) == 0


def _first_text(row: list[str]) -> str:
    return str(row[0]).strip() if row else ""


def _level_from_banner(text: str) -> str | None:
    """Return 'L1'..'L4' / 'XREF' if `text` is a section banner, else None."""
    if not _BANNER_RE.search(text):
        return None
    if "CROSS-REFERENCE" in text.upper():
        return "XREF"
    m = _LEVEL_RE.search(text)
    return m.group(1).upper() if m else None


def _trim_headers(header_row: list[str]) -> list[str]:
    """Drop trailing empty header cells; keep interior ones."""
    last = -1
    for i, cell in enumerate(header_row):
        if str(cell).strip() != "":
            last = i
    return [str(c).strip() for c in header_row[: last + 1]]


def _row_to_record(headers: list[str], row: list[str]) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    for i, name in enumerate(headers):
        rec[name] = str(row[i]).strip() if i < len(row) else ""
    return rec


def _is_number(cell: str) -> bool:
    s = str(cell).strip().replace(",", "").replace("%", "")
    if s in ("", "-"):
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _numeric_fraction(row: list[str]) -> float:
    cells = _nonempty(row)
    if not cells:
        return 0.0
    return sum(1 for c in cells if _is_number(c)) / len(cells)


def _looks_like_header(row: list[str]) -> bool:
    """A header row is almost all text labels (very few numbers) with >=2 filled cells.

    Threshold is conservative (<=0.15 numeric) so text-heavy DATA rows — e.g. equity holdings
    that carry only 3 numeric cells among ~14 (~0.21) — are never mistaken for headers.
    """
    return len(_nonempty(row)) >= 2 and _numeric_fraction(row) <= 0.15


def _segment_block(rest: list[list[str]]) -> list[tuple[list[str], list[list[str]]]]:
    """Split one blank-row block into (headers, data_rows) segments.

    Handles ADJACENT tables with no blank line between them: a later row that looks like a
    header (mostly text) and differs from the current header starts a new table.
    """
    segments: list[tuple[list[str], list[list[str]]]] = []
    cur_headers = _trim_headers(rest[0])
    cur_data: list[list[str]] = []
    for row in rest[1:]:
        if cur_data and _looks_like_header(row) and _trim_headers(row) != cur_headers:
            segments.append((cur_headers, cur_data))
            cur_headers, cur_data = _trim_headers(row), []
        else:
            cur_data.append(row)
    segments.append((cur_headers, cur_data))
    return segments


# --- main detector ------------------------------------------------------------
def detect_tables(rows: list[list[str]]) -> list[DetectedTable]:
    """Split a sheet's rows into labeled tables."""
    tables: list[DetectedTable] = []
    current_level: str | None = None
    pending_title: str | None = None

    i, n = 0, len(rows)
    while i < n:
        if _is_blank(rows[i]):
            i += 1
            continue

        # Collect a block of consecutive non-blank rows.
        block: list[list[str]] = []
        while i < n and not _is_blank(rows[i]):
            block.append(rows[i])
            i += 1

        # Peel leading banner / single-cell title lines off the block.
        idx = 0
        while idx < len(block):
            text = _first_text(block[idx])
            level = _level_from_banner(text)
            if level is not None:
                current_level = level
                idx += 1
                continue
            # A single-cell row followed by more rows is a sub-table title.
            if len(_nonempty(block[idx])) == 1 and idx + 1 < len(block):
                pending_title = text
                idx += 1
                continue
            break

        rest = block[idx:]
        if len(rest) < 2:  # need a header + at least one data row
            pending_title = None
            continue

        # One block may hold several adjacent tables (no blank line between them).
        first = True
        for headers, data in _segment_block(rest):
            if not headers:
                continue
            records = [
                _row_to_record(headers, r)
                for r in data
                if len(_nonempty(r)) > 1  # drop single-cell annotation lines
            ]
            if records:
                title = pending_title if first else None
                tables.append(DetectedTable(current_level, title, headers, records))
                first = False
        pending_title = None

    return tables
