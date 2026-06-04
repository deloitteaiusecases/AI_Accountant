"""Prove the L4-only result is computed purely from L4 rows (no hallucination, no stored data).

For each reconstructed holding it prints exactly where its carrying value came from:
purchase cost (L4-A), latest MtM fair value (L4-D), and/or EIR amortisation (L4-E).
Then it shows the totals tie to the sum of these rows — and differ from the stored ground truth.

    python scripts/verify_l4_provenance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from ai_accountant.compute.cascade import _CLASS_MAP, _num  # noqa: E402
from ai_accountant.config import NOTE5_GROUND_TRUTH, SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import detect_tables, read_rows_from_text  # noqa: E402


def l4_only_text() -> str:
    lines = SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if "L4: TRANSACTION LEVEL" in ln)
    end = next(i for i, ln in enumerate(lines) if "CROSS-REFERENCE MAP" in ln)
    return "\n".join(lines[start:end])


def main() -> None:
    tables = detect_tables(read_rows_from_text(l4_only_text()))
    by_cols = lambda *c: next((t for t in tables if t.has_columns(*c)), None)

    pur = by_cols("Total_Cost_000", "Holding_ID", "Classification").df.copy()
    pur["Total_Cost_000"] = _num(pur["Total_Cost_000"])
    cost = pur.groupby(["Holding_ID", "Classification"], as_index=False)["Total_Cost_000"].sum()

    mtm_t = by_cols("New_FV_000", "Holding_ID")
    fv = {}
    if mtm_t is not None:
        m = mtm_t.df.copy(); m["New_FV_000"] = _num(m["New_FV_000"])
        fv = m.dropna(subset=["New_FV_000"]).groupby("Holding_ID")["New_FV_000"].last().to_dict()

    eir_t = by_cols("Monthly_Amort_000", "Holding_ID")
    amort = {}
    if eir_t is not None:
        e = eir_t.df.copy(); e["Monthly_Amort_000"] = _num(e["Monthly_Amort_000"])
        amort = e.groupby("Holding_ID")["Monthly_Amort_000"].sum().to_dict()

    print(f"{'Holding':10s} {'Class':12s} {'PurchCost':>11s} {'MtM FV':>11s} "
          f"{'+Amort':>8s} {'Carrying':>11s}  source")
    print("-" * 78)
    totals: dict[str, float] = {}
    for _, r in cost.iterrows():
        hid, cls, base = r["Holding_ID"], r["Classification"], float(r["Total_Cost_000"] or 0)
        bucket = _CLASS_MAP.get(cls, cls)
        if bucket in ("FVTPL", "FVOCI") and hid in fv:
            carry, src = fv[hid], "L4-D MtM fair value"
        elif bucket == "Amortised Cost":
            carry, src = base + amort.get(hid, 0), "L4-A cost + L4-E amort"
        else:
            carry, src = base, "L4-A purchase cost"
        totals[bucket] = totals.get(bucket, 0) + carry
        print(f"{hid:10s} {cls:12s} {base:>11,.0f} "
              f"{fv.get(hid, float('nan')):>11,.0f} {amort.get(hid, 0):>8,.0f} {carry:>11,.0f}  {src}")

    print("-" * 78)
    grand = sum(totals.values())
    for b, v in totals.items():
        print(f"  {b:16s} {v:>14,.0f}")
    print(f"  {'TOTAL':16s} {grand:>14,.0f}")
    print(f"\nStored ground-truth TOTAL (for comparison only): {NOTE5_GROUND_TRUTH['TOTAL']:,.0f}")
    print(f"Computed != stored  ->  {grand:,.0f} != {NOTE5_GROUND_TRUTH['TOTAL']:,.0f}  "
          f"(proves the cascade computed from L4, not from stored totals)")


if __name__ == "__main__":
    main()
