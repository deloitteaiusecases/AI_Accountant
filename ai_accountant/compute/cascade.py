"""The L4 -> L3 -> L2 -> L1 cascade for Note 5 (Investments, Net).

Computes the headline classification totals from the lowest available level, then upward:
  * If an L3 sub-ledger is present, aggregate it (the exact path).
  * If only L4 transactions are present, REBUILD a best-effort L3 from them first
    (dynamic entry point), then aggregate.

Tables are located by COLUMN SIGNATURE, not by section banner, so a file that contains only
L4 transactions (with no "==== L4 ====" markers) still works.

Classification normalization: L3 tags equities as "FVOCI Equity"; for the Note 5 headline
these roll up into "FVOCI". "AC" is the Amortised Cost bucket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ai_accountant.ingestion.table_detect import DetectedTable

# L3 Classification value -> Note 5 headline bucket.
_CLASS_MAP = {
    "AC": "Amortised Cost",
    "FVOCI": "FVOCI",
    "FVOCI Equity": "FVOCI",
    "FVTPL": "FVTPL",
}
_BUCKETS = ("FVTPL", "FVOCI", "Amortised Cost")


@dataclass
class CascadeResult:
    l1: dict[str, float]                 # FS face: per-bucket + TOTAL (SAR '000)
    l2_classification: pd.DataFrame      # computed 5.1-style summary
    l3_holdings: pd.DataFrame            # the sub-ledger used (given or reconstructed)
    l3_source: str = "L3 sub-ledger (as provided)"
    l4_summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    partial: bool = False                # True when results may be incomplete


def _num(series: pd.Series) -> pd.Series:
    """Coerce a column to numeric, treating N/A / blanks / text as NaN."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
        errors="coerce",
    )


def _collect_by_cols(tables: list[DetectedTable], *required_cols: str) -> pd.DataFrame | None:
    """Concatenate ALL tables containing the required columns (ignores level/banner).

    This is what makes multi-file / multi-sheet work: if purchases (or holdings) are split
    across several files or sheets, every matching table is merged before aggregation.
    """
    frames = [t.df for t in tables if t.has_columns(*required_cols)]
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def _reconstruct_l3_from_l4(tables: list[DetectedTable]) -> tuple[pd.DataFrame | None, list[str]]:
    """Best-effort rebuild of the sub-ledger (carrying value per holding) from L4.

    carrying value =
      * latest fair value (from MtM revaluations) for FVTPL / FVOCI holdings, else
      * purchase cost + cumulative EIR amortisation for Amortised Cost, else
      * purchase cost.

    Excludes opening balances (holdings not transacted this period) — hence "best-effort".
    """
    df = _collect_by_cols(tables, "Total_Cost_000", "Holding_ID", "Classification")
    if df is None:
        return None, []

    df = df.copy()
    df["Total_Cost_000"] = _num(df["Total_Cost_000"])
    holdings = (
        df.groupby(["Holding_ID", "Classification"], as_index=False)["Total_Cost_000"]
        .sum()
        .rename(columns={"Total_Cost_000": "Carrying_Value_000"})
    )

    # Latest fair value per holding (file order is chronological).
    fv_map: dict[str, float] = {}
    m = _collect_by_cols(tables, "New_FV_000", "Holding_ID")
    if m is not None:
        m = m.copy()
        m["New_FV_000"] = _num(m["New_FV_000"])
        fv_map = m.dropna(subset=["New_FV_000"]).groupby("Holding_ID")["New_FV_000"].last().to_dict()

    # Cumulative EIR amortisation per holding (Amortised Cost).
    amort_map: dict[str, float] = {}
    e = _collect_by_cols(tables, "Monthly_Amort_000", "Holding_ID")
    if e is not None:
        e = e.copy()
        e["Monthly_Amort_000"] = _num(e["Monthly_Amort_000"])
        amort_map = e.groupby("Holding_ID")["Monthly_Amort_000"].sum().to_dict()

    def carry(row: pd.Series) -> float:
        hid, cls = row["Holding_ID"], row["Classification"]
        base = float(row["Carrying_Value_000"] or 0.0)
        bucket = _CLASS_MAP.get(cls, cls)
        if bucket in ("FVTPL", "FVOCI") and hid in fv_map:
            return float(fv_map[hid])
        if bucket == "Amortised Cost":
            return base + float(amort_map.get(hid, 0.0))
        return base

    holdings["Carrying_Value_000"] = holdings.apply(carry, axis=1)

    # Attach a readable security name from the L4 tables where available (richer sub-ledger).
    name_map: dict[str, str] = {}
    for src in (df, m, e):
        if src is not None and "Security" in src.columns and "Holding_ID" in src.columns:
            for hid, sec in zip(src["Holding_ID"].astype(str), src["Security"].astype(str)):
                hid, sec = hid.strip(), sec.strip()
                if hid and sec and hid not in name_map:
                    name_map[hid] = sec
    if name_map:
        holdings["Security_Name"] = holdings["Holding_ID"].astype(str).str.strip().map(name_map)

    note = (
        "No L3 sub-ledger provided — holdings were rebuilt from L4 transactions. Results reflect "
        "only the transactions in this file and EXCLUDE opening balances, so totals are partial. "
        "Add opening balances or an L3/L2 level for complete figures."
    )
    return holdings, [note]


def _sum_by_bucket(df: pd.DataFrame, value_col: str) -> dict[str, float]:
    """Sum `value_col` grouped into the three Note 5 buckets."""
    d = df.copy()
    d[value_col] = _num(d[value_col])
    d["Bucket"] = d["Classification"].map(_CLASS_MAP).fillna(d["Classification"])
    out = d.groupby("Bucket")[value_col].sum().to_dict()
    return {b: float(out.get(b, 0.0)) for b in _BUCKETS}


def _opening_by_bucket(tables: list[DetectedTable]) -> dict[str, float]:
    """Per-bucket opening balances, if an opening-balances table was provided."""
    op = _collect_by_cols(tables, "Classification", "Opening_000")
    return _sum_by_bucket(op, "Opening_000") if op is not None else {}


def _movements_by_bucket(tables: list[DetectedTable]) -> dict[str, float]:
    """Net L4 movement per bucket: + purchases − sales + MtM + EIR amortisation."""
    mv = {b: 0.0 for b in _BUCKETS}
    pur = _collect_by_cols(tables, "Total_Cost_000", "Classification")
    if pur is not None:
        for b, v in _sum_by_bucket(pur, "Total_Cost_000").items():
            mv[b] += v
    sale = _collect_by_cols(tables, "Proceeds_000", "Classification")
    if sale is not None:
        for b, v in _sum_by_bucket(sale, "Proceeds_000").items():
            mv[b] -= v
    mtm = _collect_by_cols(tables, "MtM_Change_000", "Classification")
    if mtm is not None:
        for b, v in _sum_by_bucket(mtm, "MtM_Change_000").items():
            mv[b] += v
    eir = _collect_by_cols(tables, "Monthly_Amort_000")
    if eir is not None:  # L4-E has no Classification column -> all Amortised Cost
        mv["Amortised Cost"] += float(_num(eir["Monthly_Amort_000"]).sum())
    return mv


def compute_cascade(tables: list[DetectedTable]) -> CascadeResult:
    """Run the cascade and return computed L1/L2/L3 + L4 summary."""
    notes: list[str] = []
    partial = False

    # --- Obtain L1 from L3 (given), or opening+movements, or rebuild from L4 --
    l3_df = _collect_by_cols(tables, "Holding_ID", "Classification", "Carrying_Value_000")
    if l3_df is not None:
        # (A) Exact: aggregate the provided sub-ledger.
        l3 = l3_df.copy()
        l3["Carrying_Value_000"] = _num(l3["Carrying_Value_000"])
        l3["Bucket"] = l3["Classification"].map(_CLASS_MAP).fillna(l3["Classification"])
        l3_source = "L3 sub-ledger (as provided)"
        by_bucket = l3.groupby("Bucket")["Carrying_Value_000"].sum()
        l1 = {b: float(by_bucket.get(b, 0.0)) for b in _BUCKETS}
        l2_classification = (
            l3.groupby(["Bucket", "Classification"])["Carrying_Value_000"].sum()
            .reset_index().rename(columns={"Carrying_Value_000": "Carrying_Value_000_SAR000"})
        )
    else:
        opening = _opening_by_bucket(tables)
        l3_recon, recon_notes = _reconstruct_l3_from_l4(tables)
        if l3_recon is None and not opening:
            raise ValueError(
                "Couldn't find investment data to build Note 5. Provide an L3 sub-ledger "
                "(Holding_ID + Carrying_Value_000), L4 transactions (Holding_ID + "
                "Total_Cost_000), or opening balances (Classification + Opening_000)."
            )
        if opening:
            # (B) Closing = opening balances + net L4 movements (complete, not partial).
            movements = _movements_by_bucket(tables)
            l1 = {b: opening.get(b, 0.0) + movements.get(b, 0.0) for b in _BUCKETS}
            l3_source = "opening balances + L4 movements"
            notes.append("Closing computed as opening balances + net L4 movements per "
                         "classification (purchases − sales + MtM + amortisation).")
            l2_classification = pd.DataFrame([
                {"Bucket": b, "Classification": b, "Opening_000": opening.get(b, 0.0),
                 "Net_Movement_000": movements.get(b, 0.0), "Closing_000": l1[b]}
                for b in _BUCKETS
            ])
            l3 = l3_recon if l3_recon is not None else pd.DataFrame()
        else:
            # (C) L4 only, no opening: best-effort reconstruction (partial).
            l3 = l3_recon
            l3["Bucket"] = l3["Classification"].map(_CLASS_MAP).fillna(l3["Classification"])
            l3_source = "reconstructed from L4 transactions"
            notes.extend(recon_notes)
            partial = True
            by_bucket = l3.groupby("Bucket")["Carrying_Value_000"].sum()
            l1 = {b: float(by_bucket.get(b, 0.0)) for b in _BUCKETS}
            l2_classification = (
                l3.groupby(["Bucket", "Classification"])["Carrying_Value_000"].sum()
                .reset_index().rename(columns={"Carrying_Value_000": "Carrying_Value_000_SAR000"})
            )

    l1["TOTAL"] = float(sum(l1[b] for b in _BUCKETS))

    # --- L4 transaction summary ---------------------------------------------
    l4_summary: dict[str, Any] = {}
    pur = _collect_by_cols(tables, "Total_Cost_000")
    if pur is not None:
        pur = pur.copy()
        pur["Total_Cost_000"] = _num(pur["Total_Cost_000"])
        l4_summary["purchases_total"] = float(pur["Total_Cost_000"].sum())
        if "Classification" in pur.columns:
            l4_summary["purchases_by_class"] = (
                pur.groupby("Classification")["Total_Cost_000"].sum().to_dict()
            )
    sale = _collect_by_cols(tables, "Proceeds_000")
    if sale is not None:
        l4_summary["sales_total"] = float(_num(sale["Proceeds_000"]).sum())
    inc = _collect_by_cols(tables, "Net_000", "Income_Type")
    if inc is not None:
        l4_summary["income_net_total"] = float(_num(inc["Net_000"]).sum())
    mtm = _collect_by_cols(tables, "MtM_Change_000")
    if mtm is not None:
        l4_summary["mtm_total"] = float(_num(mtm["MtM_Change_000"]).sum())

    return CascadeResult(
        l1=l1,
        l2_classification=l2_classification,
        l3_holdings=l3,
        l3_source=l3_source,
        l4_summary=l4_summary,
        notes=notes,
        partial=partial,
    )
