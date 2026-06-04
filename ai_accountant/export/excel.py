"""Excel export (openpyxl) of a computed Note 5 result.

Takes a Note5Result (duck-typed to avoid an import cycle) and writes a multi-sheet workbook:
the L1 face, the L2 classification summary, the L3 sub-ledger, the reconciliation (if any),
and the confidence controls. Returns the .xlsx as bytes for st.download_button.
"""
from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd

_L3_COLS = ["Holding_ID", "Security_Name", "Issuer", "Classification",
            "Currency", "Carrying_Value_000", "Fair_Value_000", "Maturity"]

_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")


def _unique_sheet_name(base: str, used: set[str]) -> str:
    """Excel sheet names: <=31 chars, no : \\ / ? * [ ], and unique."""
    name = _INVALID_SHEET_CHARS.sub(" ", str(base)).strip() or "table"
    name = name[:31]
    candidate, i = name, 1
    while candidate.lower() in {u.lower() for u in used}:
        suffix = f" ({i})"
        candidate = name[:31 - len(suffix)] + suffix
        i += 1
    return candidate


def build_sheets(result: Any) -> dict[str, pd.DataFrame]:
    """Assemble the named DataFrames that make up the export."""
    l1 = result.cascade.l1
    sheets: dict[str, pd.DataFrame] = {
        "Note 5 (L1)": pd.DataFrame(
            [{"Line": b, "Amount (SAR '000)": l1.get(b, 0.0)}
             for b in ["FVTPL", "FVOCI", "Amortised Cost", "TOTAL"]]
        ),
        "Classification (L2)": result.cascade.l2_classification,
    }

    l3 = result.cascade.l3_holdings
    if l3 is not None and not l3.empty:
        cols = [c for c in _L3_COLS if c in l3.columns] or list(l3.columns)
        sheets["Sub-ledger (L3)"] = l3[cols]

    recon_rows = [
        {"Level": s.level, "Item": ln.item, "Computed": ln.computed,
         "Expected (FS)": ln.expected, "Variance": ln.variance, "Status": ln.status}
        for s in (result.reconciliation_report or []) for ln in s.lines
    ]
    if recon_rows:
        sheets["Reconciliation"] = pd.DataFrame(recon_rows)

    conf = result.confidence
    if conf.controls:
        sheets["Confidence"] = pd.DataFrame(
            [{"Control": c.name, "Status": c.status, "Detail": c.detail}
             for c in conf.controls]
        )

    # Source tables exactly as detected/uploaded (full detail) — incl. the L4 transactions.
    used = set(sheets)
    for t in getattr(result, "tables", []) or []:
        if not t.records:
            continue
        base = f"{t.level or 'src'} - {t.title or (t.headers[0] if t.headers else 'table')}"
        name = _unique_sheet_name(base, used)
        used.add(name)
        sheets[name] = t.df
    return sheets


def export_to_excel(result: Any) -> bytes:
    """Return the computed Note 5 as a multi-sheet .xlsx (bytes)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in build_sheets(result).items():
            # Excel sheet names max 31 chars and can't contain some characters.
            safe = name[:31]
            df.to_excel(xw, sheet_name=safe, index=False)
    return buf.getvalue()
