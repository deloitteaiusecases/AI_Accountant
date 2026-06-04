"""Phase 2 completion tests: large-file streaming and opening-balance inputs.

    python tests/test_phase2_complete.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.compute.note5 import run_note5_from_files  # noqa: E402
from ai_accountant.compute.streaming import stream_cascade_from_csv  # noqa: E402
from ai_accountant.ingestion.loaders import iter_csv_chunks  # noqa: E402


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):
        return getattr(self.__dict__["_buf"], item)


def _big_holdings_csv(n: int) -> bytes:
    """Synthetic single-table holdings CSV: rotates through the 3 buckets, 1000 each row."""
    lines = ["Holding_ID,Classification,Carrying_Value_000"]
    classes = ["FVTPL", "FVOCI", "AC"]
    for i in range(n):
        lines.append(f"H-{i},{classes[i % 3]},1000")
    return ("\n".join(lines)).encode("utf-8")


def test_streaming_reads_in_multiple_chunks():
    data = _big_holdings_csv(250_000)
    chunks = list(iter_csv_chunks(io.BytesIO(data), chunksize=100_000))
    assert len(chunks) >= 3  # 250k / 100k -> 3 chunks
    assert sum(len(c) for c in chunks) == 250_000


def test_streaming_matches_expected_totals():
    n = 250_002  # divisible by 3 -> equal buckets
    res = stream_cascade_from_csv(io.BytesIO(_big_holdings_csv(n)), chunksize=100_000)
    per_bucket = (n // 3) * 1000
    assert res.l1["FVTPL"] == per_bucket
    assert res.l1["FVOCI"] == per_bucket
    assert res.l1["Amortised Cost"] == per_bucket
    assert res.l1["TOTAL"] == per_bucket * 3
    assert res.partial is False
    assert "chunk" in res.l3_source


def test_large_file_routed_through_streaming():
    """A large single holdings CSV uploaded via run_note5_from_files uses the streamed path."""
    up = _Upload("huge_holdings.csv", _big_holdings_csv(120_000))  # > 5 MB? ensure large
    # 120k rows * ~20 bytes ~ 2.4 MB; pad threshold check by lowering via many rows:
    up = _Upload("huge_holdings.csv", _big_holdings_csv(300_000))  # ~6 MB > 5 MB threshold
    res = run_note5_from_files([up])
    assert "streamed" in res.cascade.l3_source
    assert res.cascade.l1["TOTAL"] > 0


def test_opening_balances_complete_the_closing():
    """L4 transactions + opening balances -> complete (non-partial) closing per class."""
    opening = ("Classification,Opening_000\n"
               "FVTPL,2200000\nFVOCI,10800000\nAC,8500000\n").encode("utf-8")
    purchases = ("Txn_ID,Holding_ID,Classification,Total_Cost_000\n"
                 "PUR-1,TPL-1,FVTPL,100000\nPUR-2,OCI-1,FVOCI,200000\n"
                 "PUR-3,AC-1,AC,300000\n").encode("utf-8")
    op = _Upload("opening.csv", opening)
    pur = _Upload("purchases.csv", purchases)
    res = run_note5_from_files([op, pur])
    assert res.cascade.partial is False                     # opening makes it complete
    assert res.cascade.l3_source == "opening balances + L4 movements"
    # Closing = opening + purchases (no sales/mtm/amort here).
    assert res.cascade.l1["FVTPL"] == 2200000 + 100000
    assert res.cascade.l1["FVOCI"] == 10800000 + 200000
    assert res.cascade.l1["Amortised Cost"] == 8500000 + 300000


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
