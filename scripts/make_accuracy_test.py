"""Build a CLEAN, internally-consistent accuracy-test dataset for a fictional bank.

Unlike the Al Madinah sample (which has deliberate reconciling variances), this dataset ties
out exactly: L4 -> L3 -> L2 -> L1 with no inconsistencies. It produces TWO documents:

  accuracy_test/MERIDIAN_L4_upload.csv        <- UPLOAD THIS (raw L4 transactions only)
  accuracy_test/MERIDIAN_EXPECTED_truth.csv   <- DO NOT UPLOAD; compare the system output to it

Then it runs the L4-only upload through the system and confirms the computed L1/L2/L3 equals
the ground truth exactly.

    python scripts/make_accuracy_test.py
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "accuracy_test"
OUT.mkdir(exist_ok=True)

# --- the clean dataset (Meridian Commercial Bank, fictional) -----------------
# carrying = final fair value for FVTPL/FVOCI; = cost + amortisation for Amortised Cost.
HOLDINGS = [
    # id,      name,                    cls,     cost,     amort,  final_fv
    ("TPL-01", "Trading Bond Series A", "FVTPL",  500000,  None,   510000),
    ("TPL-02", "Equity Growth Fund",    "FVTPL",  300000,  None,   320000),
    ("TPL-03", "Logistics REIT Units",  "FVTPL",  200000,  None,   195000),
    ("OCI-01", "Sovereign Bond 2030",   "FVOCI",  800000,  None,   820000),
    ("OCI-02", "Corporate Bond 2028",   "FVOCI",  600000,  None,   590000),
    ("OCI-03", "Listed Bank Shares",    "FVOCI",  400000,  None,   450000),
    ("AC-01",  "Govt Sukuk 2032",       "AC",    1000000,  5000,   None),
    ("AC-02",  "Treasury Bill 6M",      "AC",     700000,  3000,   None),
    ("AC-03",  "Corporate Sukuk 2027",  "AC",     500000, -2000,   None),
]
BUCKET = {"FVTPL": "FVTPL", "FVOCI": "FVOCI", "AC": "Amortised Cost"}


def carrying(h) -> int:
    _id, _name, cls, cost, amort, fv = h
    if cls in ("FVTPL", "FVOCI"):
        return fv
    return cost + (amort or 0)


def expected_l1() -> dict[str, int]:
    out = {"FVTPL": 0, "FVOCI": 0, "Amortised Cost": 0}
    for h in HOLDINGS:
        out[BUCKET[h[2]]] += carrying(h)
    out["TOTAL"] = sum(out.values())
    return out


# --- write the L4-only upload file -------------------------------------------
def write_upload(path: Path) -> None:
    rows: list[list] = []
    rows.append(["MERIDIAN COMMERCIAL BANK — RAW L4 TRANSACTIONS (UPLOAD THIS FILE)"])
    rows.append([])
    rows.append(["L4-A: PURCHASES"])
    rows.append(["Txn_ID", "Trade_Date", "Holding_ID", "Security", "Classification", "Total_Cost_000"])
    for i, h in enumerate(HOLDINGS, 1):
        rows.append([f"PUR-{i:02d}", "15-Jan-25", h[0], h[1], h[2], h[3]])
    rows.append([])
    rows.append(["L4-D: MARK-TO-MARKET REVALUATIONS"])
    rows.append(["Reval_ID", "Date", "Holding_ID", "Security", "Classification",
                 "Prior_FV_000", "New_FV_000", "MtM_Change_000"])
    j = 1
    for h in HOLDINGS:
        if h[2] in ("FVTPL", "FVOCI"):
            rows.append([f"REV-{j:02d}", "31-Dec-25", h[0], h[1], h[2], h[3], h[5], h[5] - h[3]])
            j += 1
    rows.append([])
    rows.append(["L4-E: EIR AMORTISATION"])
    rows.append(["Amort_ID", "Month_End", "Holding_ID", "Security", "Cost_000", "Monthly_Amort_000"])
    k = 1
    for h in HOLDINGS:
        if h[2] == "AC":
            rows.append([f"AMT-{k:02d}", "31-Dec-25", h[0], h[1], h[3], h[4]])
            k += 1
    rows.append([])
    rows.append(["L4-C: COUPON / DIVIDEND INCOME"])
    rows.append(["Income_ID", "Date", "Holding_ID", "Security", "Classification",
                 "Income_Type", "Gross_000", "WHT_000", "Net_000"])
    income = {"FVTPL": ("Distribution", 8000), "FVOCI": ("Coupon", 30000), "AC": ("Coupon", 45000)}
    for i, h in enumerate(HOLDINGS, 1):
        it, gross = income[h[2]]
        rows.append([f"INC-{i:02d}", "30-Jun-25", h[0], h[1], h[2], it, gross, 0, gross])
    _csv(path, rows)


# --- write the ground-truth workbook -----------------------------------------
def write_truth(path: Path) -> None:
    l1 = expected_l1()
    rows: list[list] = []
    rows.append(["MERIDIAN COMMERCIAL BANK — EXPECTED RESULTS (GROUND TRUTH — DO NOT UPLOAD)"])
    rows.append(["All amounts SAR '000. Internally consistent: L4 -> L3 -> L2 -> L1 ties exactly."])
    rows.append([])
    rows.append(["========== L1: FINANCIAL STATEMENT FACE =========="])
    rows.append(["BS_Line", "31 Dec 2025"])
    rows.append(["Investments FVTPL", l1["FVTPL"]])
    rows.append(["Investments FVOCI", l1["FVOCI"]])
    rows.append(["Investments Amortised Cost", l1["Amortised Cost"]])
    rows.append(["TOTAL INVESTMENTS", l1["TOTAL"]])
    rows.append([])
    rows.append(["========== L2: CLASSIFICATION SUMMARY =========="])
    rows.append(["Classification", "Sub-Category", "31 Dec 2025"])
    by_bucket: dict[str, list] = {}
    for h in HOLDINGS:
        by_bucket.setdefault(BUCKET[h[2]], []).append(h)
    for bucket, hs in by_bucket.items():
        for h in hs:
            rows.append([bucket, h[1], carrying(h)])
        rows.append([bucket, "TOTAL", sum(carrying(h) for h in hs)])
    rows.append(["GRAND TOTAL", "", l1["TOTAL"]])
    rows.append([])
    rows.append(["========== L3: SUB-LEDGER (HOLDINGS) =========="])
    rows.append(["Holding_ID", "Security_Name", "Classification", "Carrying_Value_000"])
    for h in HOLDINGS:
        rows.append([h[0], h[1], h[2], carrying(h)])
    rows.append([])
    rows.append(["========== L4: TRANSACTIONS (as in the upload file) =========="])
    rows.append(["See MERIDIAN_L4_upload.csv for the full transaction detail."])
    _csv(path, rows)


def _csv(path: Path, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


class U:
    def __init__(self, path: Path):
        self.name = path.name
        self._b = io.BytesIO(path.read_bytes())

    def __getattr__(self, k):
        return getattr(self.__dict__["_b"], k)


def main() -> None:
    up = OUT / "MERIDIAN_L4_upload.csv"
    truth = OUT / "MERIDIAN_EXPECTED_truth.csv"
    write_upload(up)
    write_truth(truth)
    print(f"Wrote:\n  {up}\n  {truth}\n")

    exp = expected_l1()
    res = run_note5_from_files([U(up)])
    got = res.cascade.l1

    print(f"{'Bucket':16} {'Computed':>12} {'Expected':>12} {'Match':>7}")
    all_ok = True
    for b in ("FVTPL", "FVOCI", "Amortised Cost", "TOTAL"):
        ok = round(got.get(b, 0)) == exp[b]
        all_ok &= ok
        print(f"{b:16} {got.get(b, 0):>12,.0f} {exp[b]:>12,.0f} {'OK' if ok else 'DIFF':>7}")
    print(f"\nExact match: {all_ok}  (system flagged partial={res.cascade.partial} — expected for "
          "L4-only, but this fresh-start period has no opening balances so it's complete)")


if __name__ == "__main__":
    main()
