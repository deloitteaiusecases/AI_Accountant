"""Phase 3 tests: classification engine (IFRS 9 + policy override) and end-to-end.

    python tests/test_classification.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import DetectedTable  # noqa: E402
from ai_accountant.policy import (  # noqa: E402
    apply_classification,
    classify,
    normalize_classification,
)


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):
        return getattr(self.__dict__["_buf"], item)


def test_ifrs9_inference():
    assert classify("Trading Bond GCC Corp").classification == "FVTPL"
    assert classify("AMNB Money Market Fund Units").classification == "FVTPL"
    assert classify("Al Rajhi Bank Shares").classification == "FVOCI"
    assert classify("Saudi Govt Sukuk 2030").classification == "FVOCI"
    assert classify("SAMA Bills 91D").classification == "Amortised Cost"
    for desc in ("Trading Bond", "Al Rajhi Shares", "SAMA Bills 91D"):
        assert classify(desc).source == "IFRS 9"


def test_policy_overrides_ifrs9():
    rules = [{"asset_type": "sukuk", "classification": "Amortised Cost",
              "reason": "Bank policy: all sukuk held to maturity"}]
    d = classify("Saudi Govt Sukuk 2030", rules)
    assert d.classification == "Amortised Cost"
    assert d.source == "policy"
    # Without the policy, IFRS 9 would say FVOCI for the same security.
    assert classify("Saudi Govt Sukuk 2030").classification == "FVOCI"


def test_normalize_labels():
    assert normalize_classification("FVIS") == "FVTPL"
    assert normalize_classification("Held at FVOCI") == "FVOCI"
    assert normalize_classification("Amortized Cost") == "Amortised Cost"


def test_apply_fills_only_missing():
    t = DetectedTable(
        level=None, title=None,
        headers=["Holding_ID", "Security_Name", "Carrying_Value_000", "Classification"],
        records=[
            {"Holding_ID": "H1", "Security_Name": "Trading Bond",
             "Carrying_Value_000": "100", "Classification": "FVTPL"},
            {"Holding_ID": "H2", "Security_Name": "Al Rajhi Shares",
             "Carrying_Value_000": "200", "Classification": ""},
        ],
    )
    decisions = apply_classification([t])
    assert len(decisions) == 1                       # only the blank one
    assert t.records[0]["Classification"] == "FVTPL"  # existing untouched
    assert t.records[1]["Classification"] == "FVOCI"  # filled by IFRS 9


def test_missing_classification_still_computes():
    csv = ("Holding_ID,Security_Name,Carrying_Value_000\n"
           "H1,Saudi Govt Sukuk 2030,1000\n"
           "H2,Al Rajhi Bank Shares,2000\n"
           "H3,AMNB Money Market Fund,3000\n"
           "H4,SAMA Bills 91D,4000\n").encode("utf-8")
    res = run_note5_from_files([_Upload("holdings_no_class.csv", csv)])
    assert res.cascade.l1["FVOCI"] == 3000          # sukuk + shares
    assert res.cascade.l1["FVTPL"] == 3000          # money market fund
    assert res.cascade.l1["Amortised Cost"] == 4000  # bills
    assert res.cascade.l1["TOTAL"] == 10000
    assert len(res.classifications) == 4


def test_sample_classifications_untouched():
    res = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
    assert res.classifications == []                 # sample is fully classified
    assert res.cascade.l1["FVTPL"] == 2_780_000      # unchanged


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
