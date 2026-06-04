"""Build a single 'dump everything at once' bundle: ~15 unlabeled mixed files for Note 5.

Mimics the real end-state where a user uploads a pile of files with no labels: data is split
across files, mixed CSV/Excel, some with foreign column names, some multi-table, plus a couple
of irrelevant 'noise' files the system should simply ignore. Then runs the whole bundle.

    python scripts/make_bundle.py
"""
from __future__ import annotations

import csv
import io
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import pandas as pd  # noqa: E402

from ai_accountant.compute.note5 import run_note5_from_files  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import (  # noqa: E402
    detect_tables, read_rows_from_path,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bundle_test"
OUT.mkdir(exist_ok=True)
TABLES = detect_tables(read_rows_from_path(str(SAMPLE_NOTE5_CSV)))


class U:
    def __init__(self, path: Path):
        self.name = path.name
        self._b = io.BytesIO(path.read_bytes())

    def __getattr__(self, k):
        return getattr(self.__dict__["_b"], k)


def _by_level(level):
    return [t for t in TABLES if t.level == level]


def _find(has):
    return next(t for t in TABLES if t.has_columns(has))


def _write_csv(path: Path, tables, rename=None):
    rows = []
    for t in tables:
        headers = [rename.get(h, h) if rename else h for h in t.headers]
        if t.title:
            rows.append([t.title])
        rows.append(headers)
        for rec in t.records:
            rows.append([rec.get(h, "") for h in t.headers])
        rows.append([])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def _write_xlsx(path: Path, named_tables):
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for sheet, t in named_tables:
            pd.DataFrame(t.records).to_excel(xw, sheet_name=sheet[:31], index=False)


def main():
    l3 = _by_level("L3")[0]
    l4 = _by_level("L4")
    l1 = _by_level("L1")
    l2 = _by_level("L2")
    purchases = _find("Total_Cost_000")
    mtm = _find("MtM_Change_000")

    # Split the 38 holdings into two files; the second uses FOREIGN column names.
    half = len(l3.records) // 2
    a = replace(l3, records=l3.records[:half], title=None)
    b = replace(l3, records=l3.records[half:], title=None)

    _write_csv(OUT / "01_holdings_part_A.csv", [a])
    _write_csv(OUT / "02_holdings_part_B_foreign.csv", [b],
               rename={"Holding_ID": "Security ID", "Carrying_Value_000": "Carrying Value",
                       "Classification": "Asset Class", "Security_Name": "Instrument"})
    _write_csv(OUT / "03_purchases.csv", [t for t in l4 if t.has_columns("Total_Cost_000")])
    _write_csv(OUT / "04_sales.csv", [t for t in l4 if t.has_columns("Proceeds_000")])
    _write_csv(OUT / "05_income.csv", [t for t in l4 if t.has_columns("Net_000")])
    _write_xlsx(OUT / "06_mark_to_market.xlsx", [("mtm", mtm)])
    _write_csv(OUT / "07_amortisation.csv", [t for t in l4 if t.has_columns("Monthly_Amort_000")])
    _write_csv(OUT / "08_ecl.csv", [t for t in l4 if t.has_columns("ECL_000")])
    _write_csv(OUT / "09_gl_journal.csv", [t for t in l4 if t.has_columns("JE_ID")])
    _write_xlsx(OUT / "10_fs_face.xlsx", [(f"L1_{i+1}", t) for i, t in enumerate(l1)])
    _write_csv(OUT / "11_note5_disclosure_tables.csv", l2)              # 5 tables stacked in one CSV
    with open(OUT / "12_opening_balances.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Classification", "Opening_000"])
        for c, v in (("FVTPL", 2200000), ("FVOCI", 10800000), ("AC", 8500000)):
            w.writerow([c, v])

    # Two irrelevant "noise" files the system should ignore.
    with open(OUT / "13_fx_rates_noise.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Currency", "Rate_to_SAR", "As_Of"])
        for c, r in (("USD", "3.75"), ("EUR", "4.10"), ("GBP", "4.80")):
            w.writerow([c, r, "31-Dec-25"])
    with open(OUT / "14_branch_list_noise.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Branch_Code", "City", "Headcount"])
        for c, city, n in (("R01", "Riyadh", 42), ("J01", "Jeddah", 31)):
            w.writerow([c, city, n])

    # One CSV with TWO L4 tables stacked adjacent (purchases + a tiny extra), no blank line.
    p = OUT / "15_combined_misc.csv"
    _write_csv(p, [purchases])
    with open(p, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reval_ID", "Holding_ID", "Classification", "MtM_Change_000"])
        w.writerow(["REV-X1", "TPL-001", "FVTPL", "500"])

    files = sorted(OUT.glob("*"))
    print(f"Generated {len(files)} files in {OUT}:")
    for f in files:
        print(f"  {f.name}")

    print("\n=== Uploading the WHOLE bundle at once ===")
    res = run_note5_from_files([U(f) for f in files])
    c = res.cascade
    stated = [s for s in res.reconciliation_report if "stated" in s.source]
    recon = ("ties" if all(s.matched for s in stated) else "variance") if stated else "n/a"
    print(f"  tables detected : {len(res.tables)}")
    print(f"  sub-ledger src  : {c.l3_source}")
    print(f"  L1 FVTPL/FVOCI/AC/TOTAL : {c.l1['FVTPL']:,.0f} / {c.l1['FVOCI']:,.0f} / "
          f"{c.l1['Amortised Cost']:,.0f} / {c.l1['TOTAL']:,.0f}")
    print(f"  reconciliation  : {recon}")
    print(f"  confidence      : {res.confidence.level} ({len(res.confidence.controls)} controls)")
    print(f"  noise ignored?  : routing has "
          f"{sum(1 for e in res.routing.entries if e.role == 'unclassified')} unclassified table(s)")


if __name__ == "__main__":
    main()
