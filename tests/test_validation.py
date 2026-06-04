"""Phase 4 tests: multi-level reconciliation vs stated data + audit trail.

    python tests/test_validation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402


def _res():
    return run_note5_from_path(str(SAMPLE_NOTE5_CSV))


def test_reconciliation_uses_stated_levels_only():
    report = _res().reconciliation_report
    levels = {s.level for s in report}
    assert any("L1" in lv for lv in levels)          # stated FS face (sample has it)
    assert any("L2" in lv for lv in levels)          # stated classification summary
    # Must NOT compare against the bundled-sample config ground truth.
    assert not any("Ground truth" in lv for lv in levels)
    assert all(s.source == "stated in uploaded data" for s in report)


def test_stated_l1_matches_groundtruth_values():
    report = _res().reconciliation_report
    l1 = next(s for s in report if "L1" in s.level)
    by_item = {ln.item: ln for ln in l1.lines}
    # FVTPL stated == computed -> MATCH; FVOCI/AC carry the known data variances.
    assert by_item["FVTPL"].status == "MATCH"
    assert by_item["FVTPL"].expected == 2_780_000
    assert by_item["FVOCI"].variance == 100_000
    assert by_item["Amortised Cost"].variance == -59_500


def test_audit_trail_traces_bucket_to_holdings_to_txns():
    audit = _res().audit
    assert not audit.is_empty
    buckets = {b.bucket: b for b in audit.buckets}
    assert set(buckets) == {"FVTPL", "FVOCI", "Amortised Cost"}
    # FVTPL holdings should sum to the FVTPL total (the 9 TPL-* holdings = 2,780,000).
    fvtpl = buckets["FVTPL"]
    assert round(fvtpl.total) == 2_780_000
    assert len(fvtpl.holdings) == 9
    # At least one FVTPL holding has traced L4 transactions (purchase / MtM / income).
    assert any(h.transactions for h in fvtpl.holdings)
    # A purchased+revalued holding (TPL-001) should trace to multiple transaction types.
    tpl001 = next((h for h in fvtpl.holdings if h.holding_id == "TPL-001"), None)
    assert tpl001 is not None and len(tpl001.transactions) >= 2
    assert {"purchase", "mark-to-market"} & {t["type"] for t in tpl001.transactions}


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
