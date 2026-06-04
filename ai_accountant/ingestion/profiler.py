"""Profile uploaded files: headers + a few sample rows per table.

Keeps massive raw data away from the LLM — only structural metadata is ever sent.

Phase 0 preserves the original single-table-per-file behavior (migrated from the old
engine.py). Phase 2 extends this to walk every sheet of a workbook and detect MULTIPLE
stacked tables within a sheet (see table_detect.py) and to classify each table's level.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ai_accountant.config import PROFILE_SAMPLE_ROWS


def profile_uploaded_files(uploaded_files: list[Any]) -> dict[str, dict[str, Any]]:
    """Extract headers + first N rows from each uploaded CSV/Excel file.

    Returns a dict keyed by filename: {"headers": [...], "sample_data": [ {row}, ... ]}.
    On a per-file error, the value is {"error": "..."} so one bad file never aborts the batch.
    """
    profiles: dict[str, dict[str, Any]] = {}
    for file in uploaded_files:
        filename = file.name
        file.seek(0)
        try:
            if filename.lower().endswith(".csv"):
                df = pd.read_csv(file, nrows=PROFILE_SAMPLE_ROWS)
            elif filename.lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(file, nrows=PROFILE_SAMPLE_ROWS)
            else:
                continue
            profiles[filename] = {
                "headers": list(df.columns),
                "sample_data": df.to_dict(orient="records"),
            }
        except Exception as exc:  # noqa: BLE001 - report per-file, keep going
            profiles[filename] = {"error": str(exc)}
    return profiles
