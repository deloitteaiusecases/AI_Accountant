"""Generate the telecom FS from the real, pre-mapped TB_Test.xlsx through the master-FS engine.

TB_Test is a single 'TB Mapping' sheet: GL Number | 2024 | 2023 | L0 | L1 | L2, where L2 already names the
FS line. This is a PREPARER-MAPPED TB for the telecom_mobily archetype. We aggregate by (L0,L1,L2) -> the
seed concept (L1 disambiguates the current/non-current splits), apply the file's RAW-TB sign convention
(assets debit-positive; every non-asset credit-negative -> flip), close the current-year P&L+OCI result into
retained earnings (the standard book-close -- deterministic arithmetic, never an AI guess), then build the
three faces through build_master_fs_export and verify they BALANCE and tie to the published Draft FS.
"""
import sys
from collections import OrderedDict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_accountant.master_fs.seed import load_master_store
from ai_accountant.reporting.master_fs_export import build_master_fs_export

ROOT = Path(__file__).resolve().parent.parent
store = load_master_store(seed_id="telecom_mobily")


def concept_for(l0, l1, l2):
    """(L0,L1,L2) -> seed concept_id. L1 only matters for the current/non-current splits."""
    nc = "non" in l1.lower()
    s = " ".join(l2.lower().replace("–", "-").replace("�", "-").split())
    if "zakat and income tax" in s:                          # same label on BS (payable) and P&L (charge)
        return "tc_zakat_tax_payable" if l0 == "Liabilities" else "tc_zakat_tax"
    table = {
        "property and equipment": "tc_ppe", "intangible assets": "tc_intangibles",
        "right of use assets": "tc_rou", "investment in joint venture": "tc_jv",
        "contract costs": "tc_contract_costs_nc" if nc else "tc_contract_costs_c",
        "contract assets": "tc_contract_assets_nc" if nc else "tc_contract_assets_c",
        "financial and other assets": "tc_fin_other_assets_nc" if nc else "tc_fin_other_assets_c",
        "inventories": "tc_inventories", "accounts receivable": "tc_accounts_receivable",
        "due from related parties": "tc_due_from_rp", "short term murabaha": "tc_murabaha",
        "cash and cash equivalents": "tc_cash",
        "borrowings": "tc_borrowings_nc" if nc else "tc_borrowings_c",
        "lease liabilities": "tc_lease_liab_nc" if nc else "tc_lease_liab_c",
        "provision for employees' end of service benefits": "tc_eosb",
        "provision for decommissioning": "tc_decommissioning",
        "contract liabilities": "tc_contract_liab_nc" if nc else "tc_contract_liab_c",
        "financial and other liabilities": "tc_fin_other_liab_nc" if nc else "tc_fin_other_liab_c",
        "accounts payable": "tc_accounts_payable", "due to related parties": "tc_due_to_rp",
        "accrued expenses": "tc_accrued_expenses", "provisions": "tc_provisions",
        "share capital": "tc_share_cap", "statutory reserve": "tc_statutory",
        "other reserves": "tc_other_res", "retained earnings": "tc_retained",
        "revenue": "tc_revenue", "cost of revenue": "tc_cor",
        "selling and marketing expenses": "tc_sm", "general and administrative expenses": "tc_ga",
        "impairment on accounts receivable and contract assets": "tc_impairment",
        "depreciation and amortization": "tc_dep", "share in profit of joint venture": "tc_share_jv",
        "finance income": "tc_finance_income", "finance costs": "tc_finance_costs",
        "other income / (expenses), net": "tc_other_income",
        "actuarial remeasurement of employees' end of service benefits": "tc_actuarial",
        "change in fair value of equity investments": "tc_fv_equity",
        "exchange differences on translation of foreign operations": "tc_fx_translation",
        "cash flow hedge - change in fair value": "tc_cfh_change",
        "cash flow hedge - reclassified to profit or loss": "tc_cfh_reclass",
    }
    return table.get(s)                                      # None -> section header (skip)


# ---- aggregate the TB by concept, applying the raw-TB sign convention (flip every non-asset) ----
wb = openpyxl.load_workbook(ROOT / "TB_Test.xlsx", data_only=True, read_only=True)
ws = wb["TB Mapping"]
cur, pri = OrderedDict(), OrderedDict()
unmapped = []
tci_cur = tci_pri = 0.0
for r in list(ws.iter_rows(values_only=True))[2:]:
    gl, v24, v23, l0, l1, l2 = r[1], r[4] or 0.0, r[5] or 0.0, r[6], r[7], r[8]
    if gl is None or not l0 or not l2:
        continue
    cid = concept_for(str(l0), str(l1 or ""), str(l2))
    sign = 1.0 if str(l0) == "Assets" else -1.0              # flip credits to presentation-positive
    a24, a23 = sign * v24, sign * v23
    if str(l0) == "Equity - Current Year":                   # current-year result -> closes into retained
        tci_cur += a24
        tci_pri += a23
    if cid is None:
        if str(l2).strip() and "expenses" not in str(l2).lower():
            unmapped.append((str(l2), v24))
        continue
    cur[cid] = cur.get(cid, 0.0) + a24
    pri[cid] = pri.get(cid, 0.0) + a23

# close the current-year comprehensive result into retained earnings (opening + TCI = closing)
cur["tc_retained"] = cur.get("tc_retained", 0.0) + tci_cur
pri["tc_retained"] = pri.get("tc_retained", 0.0) + tci_pri

# ---- stored mapping result (preparer-mapped: account == concept; provenance preparer) ----
tb_rows, mappings = [], []
for cid in (set(cur) | set(pri)):
    c = store.get(cid)
    label = c.canonical_concept if c else cid
    tb_rows.append({"account": cid, "label": label,
                    "current": round(cur.get(cid, 0.0)), "prior": round(pri.get(cid, 0.0))})
    mappings.append({"account": cid, "concept_id": cid, "client_label": label, "provenance": "preparer"})
stored = {"client": "tb-test", "master_id": "telecom_mobily", "extensions": [],
          "tb": tb_rows, "mappings": mappings}

model = build_master_fs_export(store, stored, bank="TB_Test (telecom)", unit="SAR'000",
                               period_current="31 Dec 2024", period_prior="31 Dec 2023")


def L(stk, cid):
    return next((l.current for l in model.statements[stk] if l.concept_id == cid), None)


print("Unmapped (non-header) TB lines:", unmapped or "none")
for stk, lines in model.statements.items():
    print(f"\n===== {model.statement_titles.get(stk, stk)}  (SAR'000) =====")
    print(f"{'Line':52}{'2024':>16}{'2023':>16}")
    section = None
    for l in lines:
        if l.section != section:
            section = l.section
            print(f"-- {section} --")
        c = "" if l.current is None else f"{l.current:>16,.0f}"
        p = "" if l.prior is None else f"{l.prior:>16,.0f}"
        mark = "* " if l.derived else "  "
        print(f"{mark}{l.label[:50]:50}{c}{p}")

print("\n===== TIE-OUT vs the published Draft FS =====")
checks = [
    ("Total assets 2024", L("balance_sheet", "tc_total_assets"), 38515028),
    ("Total equity 2024", L("balance_sheet", "tc_total_equity"), 18875492),
    ("Total liabilities 2024", L("balance_sheet", "tc_total_liabilities"), 19639536),
    ("Equity+Liab 2024", L("balance_sheet", "tc_total_oe"), 38515028),
    ("Net profit 2024", L("income_statement", "tc_net_profit"), 3106848),
    ("Total comprehensive income 2024", L("comprehensive_income", "tc_total_ci"), 3062385),
]
ok = True
for name, got, exp in checks:
    g = None if got is None else round(got)
    match = (g == exp)
    ok &= match
    print(f"  {'PASS' if match else 'FAIL'}  {name:34} got {g:>14,} | published {exp:>14,}")
diff = round(L("balance_sheet", "tc_total_assets") - L("balance_sheet", "tc_total_oe"))
print(f"\n  SOFP balance (assets - equity&liab): {diff}  -> {'BALANCES' if diff == 0 else 'DOES NOT BALANCE'}")
print(f"  engine balance findings: {len([f for f in model.findings if str(f[0]) == 'balance check'])}"
      f" | total findings: {len(model.findings)}")
print("\nRESULT:", "ALL TIE-OUTS PASS -- generated FS == published Draft FS"
      if ok and diff == 0 else "MISMATCH -- see above")

# ---- export the generated FS to PDF + Excel ----
from ai_accountant.reporting.master_fs_export import export_master_fs_excel, export_master_fs_pdf

out = ROOT / "exports"
out.mkdir(exist_ok=True)
xlsx, pdf = out / "FS_TB_Test_telecom.xlsx", out / "FS_TB_Test_telecom.pdf"
export_master_fs_excel(model, str(xlsx))
export_master_fs_pdf(model, str(pdf))
print(f"\nExported:\n  {xlsx}  ({xlsx.stat().st_size:,} bytes)\n  {pdf}  ({pdf.stat().st_size:,} bytes)")
