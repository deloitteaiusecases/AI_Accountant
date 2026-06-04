"""Verify the POC-hardening items: new controls + streamed confidence."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402


class U:
    def __init__(self, name, data):
        self.name = name
        self._b = io.BytesIO(data)

    def __getattr__(self, k):
        return getattr(self.__dict__["_b"], k)


def main():
    r = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    print(f"SAMPLE: level={r.confidence.level} controls={len(r.confidence.controls)} "
          f"cross_source={any('Cross-source' in c.name for c in r.confidence.controls)}")

    lines = SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig").splitlines()
    s = next(i for i, l in enumerate(lines) if "L4: TRANSACTION LEVEL" in l)
    e = next(i for i, l in enumerate(lines) if "CROSS-REFERENCE MAP" in l)
    op = U("op.csv", b"Classification,Opening_000\nFVTPL,2200000\nFVOCI,10800000\nAC,8500000\n")
    l4 = U("l4.csv", "\n".join(lines[s:e]).encode())
    r2 = run_note5_from_files([op, l4])
    print(f"OPENING+L4: roll_forward={any('Roll-forward' in c.name for c in r2.confidence.controls)}")

    classes = ["FVTPL", "FVOCI", "AC"]
    rows = ["Holding_ID,Security_Name,Classification,Carrying_Value_000"]
    rows += [f"H-{i},Security {i},{classes[i % 3]},1000" for i in range(300_000)]
    big = U("big.csv", ("\n".join(rows)).encode())
    r3 = run_note5_from_files([big])
    print(f"STREAMED: level={r3.confidence.level} controls={len(r3.confidence.controls)} "
          f"source={r3.cascade.l3_source[:30]}")


if __name__ == "__main__":
    main()
