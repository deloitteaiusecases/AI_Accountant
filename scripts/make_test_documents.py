"""Build a structured library of test cases under test_documents/case_NN_.../.

Each case folder contains the input file(s) you upload PLUS an EXPECTED_OUTPUT.txt to compare
against. All cases use one CLEAN, internally-consistent fictional dataset (Meridian Commercial
Bank) that ties out to TOTAL 5,091,000 — so the expected answer is known and the same across the
shape-only variations. A few cases deliberately differ (large streamed; missing classifications).

    python scripts/make_test_documents.py
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from ai_accountant.compute.note5 import run_note5_from_files  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "test_documents"
BASE.mkdir(exist_ok=True)

# id, name, cls, cost, amort, final_fv   (carrying = fv for FVTPL/FVOCI; cost+amort for AC)
HOLDINGS = [
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


def carry(h):
    return h[5] if h[2] in ("FVTPL", "FVOCI") else h[3] + (h[4] or 0)


# --- table builders: each returns (title, headers, rows) ----------------------
def t_purchases():
    rows = [[f"PUR-{i:02d}", "15-Jan-25", h[0], h[1], h[2], h[3]] for i, h in enumerate(HOLDINGS, 1)]
    return ("L4-A: PURCHASES",
            ["Txn_ID", "Trade_Date", "Holding_ID", "Security", "Classification", "Total_Cost_000"], rows)


def t_mtm():
    rows = [[f"REV-{i:02d}", "31-Dec-25", h[0], h[1], h[2], h[3], h[5], h[5] - h[3]]
            for i, h in enumerate([x for x in HOLDINGS if x[2] in ("FVTPL", "FVOCI")], 1)]
    return ("L4-D: MARK-TO-MARKET",
            ["Reval_ID", "Date", "Holding_ID", "Security", "Classification",
             "Prior_FV_000", "New_FV_000", "MtM_Change_000"], rows)


def t_eir():
    rows = [[f"AMT-{i:02d}", "31-Dec-25", h[0], h[1], h[3], h[4]]
            for i, h in enumerate([x for x in HOLDINGS if x[2] == "AC"], 1)]
    return ("L4-E: EIR AMORTISATION",
            ["Amort_ID", "Month_End", "Holding_ID", "Security", "Cost_000", "Monthly_Amort_000"], rows)


def t_income():
    inc = {"FVTPL": ("Distribution", 8000), "FVOCI": ("Coupon", 30000), "AC": ("Coupon", 45000)}
    rows = [[f"INC-{i:02d}", "30-Jun-25", h[0], h[1], h[2], inc[h[2]][0], inc[h[2]][1], 0, inc[h[2]][1]]
            for i, h in enumerate(HOLDINGS, 1)]
    return ("L4-C: COUPON / DIVIDEND INCOME",
            ["Income_ID", "Date", "Holding_ID", "Security", "Classification",
             "Income_Type", "Gross_000", "WHT_000", "Net_000"], rows)


def t_l3(drop_class=False, rename=None):
    headers = ["Holding_ID", "Security_Name", "Classification", "Carrying_Value_000"]
    if rename:
        headers = [rename.get(h, h) for h in headers]
    rows = [[h[0], h[1], "" if drop_class else h[2], carry(h)] for h in HOLDINGS]
    return (None, headers, rows)


def t_l1():
    b = {"FVTPL": 0, "FVOCI": 0, "Amortised Cost": 0}
    for h in HOLDINGS:
        b[{"FVTPL": "FVTPL", "FVOCI": "FVOCI", "AC": "Amortised Cost"}[h[2]]] += carry(h)
    return ("L1: FS FACE", ["BS_Line", "31 Dec 2025"],
            [["Investments FVTPL", b["FVTPL"]], ["Investments FVOCI", b["FVOCI"]],
             ["Investments Amortised Cost", b["Amortised Cost"]],
             ["TOTAL INVESTMENTS", sum(b.values())]])


def t_l2():
    rows, grand = [], 0
    for bucket, cls in (("FVTPL", "FVTPL"), ("FVOCI", "FVOCI"), ("Amortised Cost", "AC")):
        hs = [h for h in HOLDINGS if h[2] == cls]
        for h in hs:
            rows.append([bucket, h[1], carry(h)])
        st = sum(carry(h) for h in hs)
        rows.append([bucket, "TOTAL", st]); grand += st
    rows.append(["GRAND TOTAL", "", grand])
    return ("L2: CLASSIFICATION SUMMARY", ["Classification", "Sub-Category", "31 Dec 2025"], rows)


# --- writers ------------------------------------------------------------------
def stack_csv(path, *tables):
    rows = []
    for title, headers, body in tables:
        if title:
            rows.append([title])
        rows.append(headers)
        rows.extend(body)
        rows.append([])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def xlsx(path, sheets):
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, (title, headers, body) in sheets:
            pd.DataFrame(body, columns=headers).to_excel(xw, sheet_name=name[:31], index=False)


class U:
    def __init__(self, p: Path):
        self.name = p.name
        self._b = io.BytesIO(p.read_bytes())

    def __getattr__(self, k):
        return getattr(self.__dict__["_b"], k)


def write_expected(folder: Path, desc: str, inputs: list[Path], note: str = ""):
    res = run_note5_from_files([U(p) for p in inputs])
    c = res.cascade
    stated = [s for s in res.reconciliation_report if "stated" in s.source]
    recon = ("ties exactly" if all(s.matched for s in stated) else "variance") if stated else "n/a (no stated FS in upload)"
    lines = [
        f"CASE: {desc}",
        f"Upload file(s): {', '.join(p.name for p in inputs)}",
        "",
        "EXPECTED OUTPUT (all amounts SAR '000)",
        "-" * 50,
        "L1 — Financial statement face:",
        f"  FVTPL            {c.l1['FVTPL']:>14,.0f}",
        f"  FVOCI            {c.l1['FVOCI']:>14,.0f}",
        f"  Amortised Cost   {c.l1['Amortised Cost']:>14,.0f}",
        f"  TOTAL            {c.l1['TOTAL']:>14,.0f}",
        "",
        "L2 — classification summary:",
        c.l2_classification.to_string(index=False),
        "",
        "Flags:",
        f"  sub-ledger source : {c.l3_source}",
        f"  partial           : {c.partial}",
        f"  reconciliation    : {recon}",
        f"  confidence        : {res.confidence.level}",
        f"  tables detected   : {len(res.tables)}",
    ]
    if note:
        lines += ["", "Note:", "  " + note]
    (folder / "EXPECTED_OUTPUT.txt").write_text("\n".join(lines), encoding="utf-8")
    return res


def case(n, name) -> Path:
    f = BASE / f"case_{n:02d}_{name}"
    f.mkdir(exist_ok=True)
    return f


def main():
    summary = []

    # 1) Full single file (L1+L2+L3+L4) — clean, so reconciliation ties exactly.
    f = case(1, "full_single_file")
    stack_csv(f / "meridian_full.csv", t_l1(), t_l2(), t_l3(), t_purchases(), t_mtm(), t_eir(), t_income())
    r = write_expected(f, "Full multi-level single file (clean)", [f / "meridian_full.csv"])
    summary.append((1, r))

    # 2) L4-only single file.
    f = case(2, "l4_only")
    stack_csv(f / "meridian_L4.csv", t_purchases(), t_mtm(), t_eir(), t_income())
    r = write_expected(f, "L4-only (reconstructs L3/L2/L1)", [f / "meridian_L4.csv"],
                       "Flagged partial: L4-only can't know if opening balances are missing; "
                       "here the period starts fresh so it's complete and ties to 5,091,000.")
    summary.append((2, r))

    # 3) L4 split across 4 files.
    f = case(3, "l4_split_across_files")
    stack_csv(f / "purchases.csv", t_purchases())
    stack_csv(f / "mark_to_market.csv", t_mtm())
    stack_csv(f / "amortisation.csv", t_eir())
    stack_csv(f / "income.csv", t_income())
    r = write_expected(f, "L4 split across 4 files (multi-file merge)",
                       [f / "purchases.csv", f / "mark_to_market.csv", f / "amortisation.csv", f / "income.csv"])
    summary.append((3, r))

    # 4) L3 sub-ledger only.
    f = case(4, "l3_only")
    stack_csv(f / "holdings.csv", t_l3())
    r = write_expected(f, "L3 sub-ledger only (exact path)", [f / "holdings.csv"])
    summary.append((4, r))

    # 5) Foreign column names.
    f = case(5, "foreign_columns")
    stack_csv(f / "holdings_foreign.csv",
              t_l3(rename={"Holding_ID": "Security ID", "Carrying_Value_000": "Carrying Value",
                           "Classification": "Asset Class", "Security_Name": "Instrument"}))
    r = write_expected(f, "Foreign column names (normalized to canonical)", [f / "holdings_foreign.csv"])
    summary.append((5, r))

    # 6) Multi-sheet Excel.
    f = case(6, "multisheet_excel")
    xlsx(f / "meridian.xlsx", [("holdings", t_l3()), ("purchases", t_purchases()),
                               ("mtm", t_mtm()), ("amort", t_eir())])
    r = write_expected(f, "Multi-sheet Excel workbook", [f / "meridian.xlsx"])
    summary.append((6, r))

    # 7) Multiple tables stacked in one CSV.
    f = case(7, "multitable_one_csv")
    stack_csv(f / "everything_stacked.csv", t_l3(), t_purchases(), t_mtm(), t_eir())
    r = write_expected(f, "Several tables stacked in one CSV", [f / "everything_stacked.csv"])
    summary.append((7, r))

    # 8) Adjacent tables, no blank line between them.
    f = case(8, "adjacent_tables")
    p = f / "adjacent.csv"
    stack_csv(p, t_l3())
    with open(p, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Txn_ID", "Holding_ID", "Classification", "Total_Cost_000"])
        w.writerow(["PUR-X", "TPL-01", "FVTPL", "500000"])
    r = write_expected(f, "Adjacent tables with no blank line", [p])
    summary.append((8, r))

    # 9) Bundled 'dump everything' (split holdings + foreign + L1/L2 + noise).
    f = case(9, "bundled_everything")
    half = len(HOLDINGS) // 2
    g1 = (None, ["Holding_ID", "Security_Name", "Classification", "Carrying_Value_000"],
          [[h[0], h[1], h[2], carry(h)] for h in HOLDINGS[:half]])
    g2 = (None, ["Security ID", "Instrument", "Asset Class", "Carrying Value"],
          [[h[0], h[1], h[2], carry(h)] for h in HOLDINGS[half:]])
    stack_csv(f / "holdings_A.csv", g1)
    stack_csv(f / "holdings_B_foreign.csv", g2)
    stack_csv(f / "purchases.csv", t_purchases())
    stack_csv(f / "fs_face.csv", t_l1())
    stack_csv(f / "note5_summary.csv", t_l2())
    stack_csv(f / "fx_rates_NOISE.csv", ("FX RATES", ["Currency", "Rate"], [["USD", "3.75"], ["EUR", "4.1"]]))
    stack_csv(f / "branches_NOISE.csv", ("BRANCHES", ["Code", "City"], [["R1", "Riyadh"]]))
    r = write_expected(f, "Bundled 'dump everything' (15-ish mixed files, 2 noise)",
                       sorted(f.glob("*.csv")),
                       "Two NOISE files (fx_rates, branches) are correctly ignored; clean data "
                       "means reconciliation TIES exactly (no variance).")
    summary.append((9, r))

    # 10) Large streamed file (different, synthetic totals).
    f = case(10, "large_streamed")
    p = f / "large_holdings.csv"
    classes = ["FVTPL", "FVOCI", "AC"]
    rows = ["Holding_ID,Security_Name,Classification,Carrying_Value_000"]
    rows += [f"H-{i},Security {i},{classes[i % 3]},1000" for i in range(200_000)]
    p.write_text("\n".join(rows), encoding="utf-8")
    r = write_expected(f, "Large file (200k rows -> memory-bounded streaming)", [p],
                       "Synthetic: 200,000 holdings x 1,000 across 3 buckets. Streamed path.")
    summary.append((10, r))

    # 11) Opening balances + L4.
    f = case(11, "opening_plus_l4")
    with open(f / "opening.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Classification", "Opening_000"])
        for c2, v in (("FVTPL", 1000000), ("FVOCI", 1500000), ("AC", 2000000)):
            w.writerow([c2, v])
    stack_csv(f / "L4.csv", t_purchases(), t_mtm(), t_eir())
    r = write_expected(f, "Opening balances + L4 movements (complete, not partial)",
                       [f / "opening.csv", f / "L4.csv"],
                       "Closing = opening + net L4 movements; a roll-forward control checks it.")
    summary.append((11, r))

    # 12) Missing classifications -> IFRS 9 inference (split shifts; total still ties).
    f = case(12, "missing_classifications")
    stack_csv(f / "holdings_no_class.csv", t_l3(drop_class=True))
    r = write_expected(f, "Missing classifications (IFRS 9 inference)", [f / "holdings_no_class.csv"],
                       "No policy uploaded -> IFRS 9 infers from names. Sukuks default to FVOCI "
                       "(no 'held to maturity' wording), so AC shrinks and FVOCI grows vs the true "
                       "split, though TOTAL still ties to 5,091,000. Upload a policy to correct this.")
    summary.append((12, r))

    print(f"Generated {len(summary)} cases under {BASE}\n")
    print(f"{'Case':5} {'FVTPL':>12} {'FVOCI':>12} {'Amort.Cost':>12} {'TOTAL':>12} "
          f"{'partial':>8} {'conf':>7}")
    for n, r in summary:
        c = r.cascade.l1
        print(f"{n:<5} {c['FVTPL']:>12,.0f} {c['FVOCI']:>12,.0f} {c['Amortised Cost']:>12,.0f} "
              f"{c['TOTAL']:>12,.0f} {str(r.cascade.partial):>8} {r.confidence.level:>7}")


if __name__ == "__main__":
    main()
