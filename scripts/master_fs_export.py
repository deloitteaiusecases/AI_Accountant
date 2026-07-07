"""Produce the detailed master-FS PDF + Excel by REPLAYING the stored live-mapped result (no live call).

    python scripts/master_fs_export.py   ->   exports/Master_FS.xlsx , exports/Master_FS.pdf
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                        # noqa: BLE001
    pass

from ai_accountant.master_fs import load_master_store
from ai_accountant.reporting.master_fs_export import (build_master_fs_export, export_master_fs_excel,
                                                      export_master_fs_pdf)

STORED = ROOT / "exports" / "master_fs_live.json"


def main():
    if not STORED.exists():
        print("run scripts/master_fs_live_map.py first (it does the live mapping + stores the result)")
        return
    stored = json.loads(STORED.read_text(encoding="utf-8"))
    model = build_master_fs_export(load_master_store(), stored, bank="aljazira")

    print(f"=== Master-FS export (replayed from stored live mapping by {stored.get('model')}) ===")
    for st, lines in model.statements.items():
        print(f"\n{st.upper()}  (current · prior)")
        for l in lines:
            cur = "—" if l.current is None else f"{l.current:,.0f}"
            pri = "—" if l.prior is None else f"{l.prior:,.0f}"
            tag = "  [AI ASSUMPTION]" if l.ai_assumed else ""
            print(f"  [{l.section[:11]:<11}] {l.label[:40]:<40} {cur:>13} {pri:>13}{tag}")
    print(f"\nProvenance rows: {len(model.provenance)}  ·  findings: {len(model.findings)}  ·  "
          f"NOT-FINAL footnote: {model.not_final}")
    for a, lbl, reason in model.findings:
        print(f"  finding: {a} {lbl!r} — {reason}")

    out = ROOT / "exports"
    x = export_master_fs_excel(model, str(out / "Master_FS.xlsx"))
    p = export_master_fs_pdf(model, str(out / "Master_FS.pdf"))
    print(f"\nWROTE: {x}\nWROTE: {p}")


if __name__ == "__main__":
    main()
