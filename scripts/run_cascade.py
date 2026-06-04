"""Run the Note 5 cascade on the bundled sample and print results.

    python scripts/run_cascade.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402


def main() -> None:
    res = run_note5_from_path(str(SAMPLE_NOTE5_CSV))

    print("=== Detected tables (by level) ===")
    for lvl, count in res.table_counts().items():
        print(f"  {lvl}: {count}")
    print(f"  total tables: {len(res.tables)}")

    print("\n=== Computed L1 (from L3 carrying values, SAR '000) ===")
    for k, v in res.cascade.l1.items():
        print(f"  {k:16s} {v:>14,.0f}")

    print("\n=== L4 transaction summary ===")
    for k, v in res.cascade.l4_summary.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"      {kk:18s} {vv:>14,.0f}")
        else:
            print(f"  {k:18s} {v:>14,.0f}")

    print("\n=== Reconciliation vs stated ground truth ===")
    for line in res.reconciliation:
        flag = "OK " if line.status == "MATCH" else "!! "
        print(
            f"  {flag}{line.item:16s} computed={line.computed:>14,.0f} "
            f"expected={line.expected:>14,.0f} variance={line.variance:>+12,.0f}"
        )
    print(f"\nAll levels reconciled exactly: {res.reconciled}")


if __name__ == "__main__":
    main()
