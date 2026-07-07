"""Telecom (Mobily) seed — end-to-end proof via the orchestrator, LIVE.

Authors a small illustrative, balanced telecom TB (NEVER Mobily's real published figures), runs
`generate_master_fs(strategy="automap", seed_id="telecom_mobily", ...)` — which makes a REAL
`gpt-5.1-2025-11-13` mapping call (labels only) — then derives + renders all three statements and
exports. The master stays `ai_proposed_unconfirmed`; every AI mapping is `ai_assumed`, so the documents
are honestly NOT-FINAL. The LLM call is instrumented so the request (no amounts), response, and model
string are visible — proving the live path is real, not mocked or replayed.

    python scripts/master_fs_telecom_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

import ai_accountant.llm.client as llm
from ai_accountant.master_fs import generate_master_fs, load_master_store
from ai_accountant.reporting.master_fs_export import export_master_fs_excel, export_master_fs_pdf

M = 1_000  # illustrative round numbers (NOT Mobily's real figures); expenses/zakat/tax stored NEGATIVE
ROWS = [
    # account, telecom-worded label, current, prior   (BS balances: assets 66,000 == equity 40,000 + liab 26,000)
    ("1010", "Property and equipment, net", 40_000 * M, 38_000 * M),
    ("1020", "Intangible assets", 8_000 * M, 8_500 * M),
    ("1030", "Right-of-use assets", 5_000 * M, 5_200 * M),
    ("1110", "Accounts receivable, net", 6_000 * M, 5_500 * M),
    ("1120", "Short-term Murabaha placements", 3_000 * M, 2_500 * M),
    ("1130", "Cash and cash equivalents", 4_000 * M, 3_800 * M),
    ("3010", "Share capital", 30_000 * M, 30_000 * M),
    ("3020", "Statutory reserve", 5_000 * M, 4_600 * M),
    ("3030", "Retained earnings", 5_000 * M, 3_400 * M),                 # illustrative balancing figure
    ("2010", "Borrowings — non-current portion", 12_000 * M, 13_000 * M),
    ("2020", "Lease liabilities — non-current", 4_000 * M, 4_200 * M),
    ("2030", "Provision for employees' end of service benefits", 2_000 * M, 1_800 * M),
    ("2110", "Accounts payable", 5_000 * M, 4_500 * M),
    ("2120", "Zakat and income tax payable", 1_000 * M, 900 * M),
    ("2130", "Accrued expenses", 2_000 * M, 1_900 * M),
    # income statement (expenses negative)
    ("4010", "Revenue from telecom services", 30_000 * M, 28_000 * M),
    ("4020", "Cost of revenue", -18_000 * M, -17_000 * M),
    ("4030", "Selling and marketing expenses", -3_000 * M, -2_800 * M),
    ("4040", "General and administrative expenses", -2_000 * M, -1_900 * M),
    ("4050", "Depreciation and amortization", -4_000 * M, -3_900 * M),
    ("4060", "Finance costs", -800 * M, -850 * M),
    ("4070", "Finance income", 200 * M, 180 * M),
    ("4080", "Zakat and income tax expense", -400 * M, -360 * M),
    # OCI
    ("5010", "Net profit for the year", 2_000 * M, 1_400 * M),
    ("5020", "Exchange differences on translation of foreign operations", 100 * M, -60 * M),
    ("5030", "Actuarial remeasurement of end-of-service benefits", -50 * M, 30 * M),
]


def main():
    out = ROOT / "exports"; out.mkdir(exist_ok=True)
    items = [(a, lbl) for a, lbl, _c, _p in ROWS]
    tb_rows = [{"account": a, "label": lbl, "current": c, "prior": p} for a, lbl, c, p in ROWS]

    # ---- instrument the LLM client to PROVE this is a real, fresh call (not mock/replay) ----
    calls = []
    _orig = llm.LLMClient.complete_json

    def _capture(self, prompt, system=None, max_retries=3):
        resp = _orig(self, prompt, system=system, max_retries=max_retries)
        calls.append({"model": self.model, "system": system, "prompt": prompt, "response": resp})
        return resp
    llm.LLMClient.complete_json = _capture

    print("=== LIVE automap via generate_master_fs(seed_id='telecom_mobily') ===")
    res = generate_master_fs((items, tb_rows), seed_id="telecom_mobily", client="demo",
                             period=("31 December 2024", "31 December 2023"), strategy="automap",
                             bank=None, at="2026-06-14")
    llm.LLMClient.complete_json = _orig
    model = res.model

    # ---- live-call evidence ----
    print(f"\nLLM calls made on this (automap) path: {len(calls)}  (replay would be 0)")
    c0 = calls[0]
    print(f"model string sent: {c0['model']!r}")
    amount_tokens = [str(abs(c)) for *_, c, _ in ROWS] + [f"{abs(c):,}" for *_, c, _ in ROWS]
    leaked = [t for t in amount_tokens if t and t in c0["prompt"]]
    print(f"monetary amounts present in the request payload: {leaked or 'NONE (labels/codes only)'}")
    print("first 4 lines of the user payload (account <tab> label — no amounts):")
    for ln in c0["prompt"].splitlines()[-len(ROWS):][:4]:
        print("   ", ln)

    # ---- render result: all three statements + balance check ----
    for st in model.statement_titles:
        ta = sum(1 for l in model.statements[st])
        print(f"\n-- {model.statement_titles[st]} ({ta} lines) --")
        last = None
        for l in model.statements[st]:
            tag = "[DERIVED]" if l.derived else ("[ai_assumed]" if l.ai_assumed else "")
            cur = "—" if l.current is None else f"{l.current:,.0f}"
            print(f"     {l.label[:46]:<46} {cur:>14}  {tag}")
    bal = [f for f in model.findings if f[0] == "balance check"]
    print(f"\nbalance check: {'BALANCES (difference 0)' if not bal else bal[0][2]}")
    print(f"findings: {len(model.findings)} | NOT-FINAL: {model.not_final}")

    # ---- provenance honesty ----
    seed = json.loads((ROOT / 'seeds' / 'master_fs_telecom_seed.json').read_text(encoding='utf-8'))
    print(f"\nseed provenance_seed (unchanged): {seed.get('provenance_seed')!r}")

    try:
        export_master_fs_excel(model, str(out / "Master_FS_telecom_mobily.xlsx"))
        export_master_fs_pdf(model, str(out / "Master_FS_telecom_mobily.pdf"))
        print("documents written: Master_FS_telecom_mobily.{xlsx,pdf}")
    except PermissionError:
        print("[skip write — file open/locked]")


if __name__ == "__main__":
    main()
