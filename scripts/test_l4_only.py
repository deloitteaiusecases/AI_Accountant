"""Simulate an L4-only upload: slice just the L4 section from the sample, then run the
cascade and confirm it reconstructs L3 and produces (partial) totals without crashing.

    python scripts/test_l4_only.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
L4_ONLY = ROOT / "sample_data" / "_l4_only_example.csv"


def make_l4_only() -> None:
    lines = SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if "L4: TRANSACTION LEVEL" in ln)
    end = next(i for i, ln in enumerate(lines) if "CROSS-REFERENCE MAP" in ln)
    L4_ONLY.write_text("\n".join(lines[start:end]), encoding="utf-8")


def main() -> None:
    make_l4_only()
    res = run_note5_from_path(str(L4_ONLY))
    print(f"partial = {res.cascade.partial}")
    print(f"l3_source = {res.cascade.l3_source}")
    print(f"reconstructed holdings = {len(res.cascade.l3_holdings)}")
    print("\nComputed L1 (partial, SAR '000):")
    for k, v in res.cascade.l1.items():
        print(f"  {k:16s} {v:>14,.0f}")
    print("\nNotes:")
    for n in res.cascade.notes:
        print(f"  - {n}")
    L4_ONLY.unlink(missing_ok=True)
    assert res.cascade.partial is True
    assert res.cascade.l1["TOTAL"] > 0
    print("\n[ok] L4-only path works without crashing and flags partial results.")


if __name__ == "__main__":
    main()
