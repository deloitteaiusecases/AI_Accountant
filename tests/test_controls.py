"""Phase 4b tests: internal-controls confidence without an answer key.

    python tests/test_controls.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):
        return getattr(self.__dict__["_buf"], item)


def test_sample_passes_all_controls_high_confidence():
    conf = run_note5_from_path(str(SAMPLE_NOTE5_CSV)).confidence
    assert conf.controls, "no controls ran"
    assert conf.level == "High", [(c.name, c.status) for c in conf.controls]
    # Key controls present.
    names = {c.name for c in conf.controls}
    assert "Double-entry integrity (GL journals)" in names
    assert any("orphan" in n for n in names)
    assert any("GL postings" in n for n in names)


def test_no_misleading_ground_truth_for_real_upload():
    """A real holdings upload (not the sample) must NOT be reconciled to the AMNB sample totals."""
    csv = ("Holding_ID,Security_Name,Classification,Carrying_Value_000\n"
           "H1,Some Bond,FVOCI,5000\n"
           "H2,Some Shares,FVOCI,7000\n").encode("utf-8")
    res = run_note5_from_files([_Upload("my_holdings.csv", csv)])
    # No stated L1/L2 in this upload -> reconciliation report is empty (no AMNB comparison).
    assert res.reconciliation_report == []
    # Trust instead comes from the confidence report.
    assert res.confidence.controls


def test_l4_only_flags_orphans_medium_confidence():
    """L4-only (no opening) reconstructs a partial sub-ledger -> income txns become orphans."""
    lines = SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if "L4: TRANSACTION LEVEL" in ln)
    end = next(i for i, ln in enumerate(lines) if "CROSS-REFERENCE MAP" in ln)
    l4_only = "\n".join(lines[start:end]).encode("utf-8")
    res = run_note5_from_files([_Upload("l4_only.csv", l4_only)])
    conf = res.confidence
    orphan_ctrl = next((c for c in conf.controls if "orphan" in c.name), None)
    assert orphan_ctrl is not None and orphan_ctrl.status == "warn"
    assert conf.level in ("Medium", "Low")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[pass] {name}")
            except AssertionError as exc:
                failures += 1
                print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[ERROR] {name}: {exc}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
