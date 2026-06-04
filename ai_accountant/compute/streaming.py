"""Memory-bounded cascade for very large single-table holdings files.

Reads the file in chunks and accumulates the classification totals incrementally, so a
1M+ row sub-ledger never has to fit in memory at once. Produces the same CascadeResult shape
as the in-memory path, so the rest of the app (reconcile, UI) is unchanged.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ai_accountant.compute.cascade import _BUCKETS, _CLASS_MAP, _num, CascadeResult
from ai_accountant.ingestion.loaders import first_line, iter_csv_chunks
from ai_accountant.ingestion.normalize import canonical_for


def looks_like_large_holdings(file_or_path: Any) -> bool:
    """True if the header (after canonicalization) has the columns we can stream-aggregate."""
    cols = {canonical_for(c.strip()) for c in first_line(file_or_path).split(",")}
    return "Carrying_Value_000" in cols and "Classification" in cols


def stream_cascade_from_csv(file_or_path: Any, chunksize: int = 100_000) -> CascadeResult:
    """Compute L1 classification totals from a large holdings CSV, chunk by chunk."""
    bucket_totals: dict[str, float] = {b: 0.0 for b in _BUCKETS}
    detail: dict[tuple[str, str], float] = {}
    rows_seen = 0
    chunks_seen = 0
    head_sample: pd.DataFrame | None = None

    for chunk in iter_csv_chunks(file_or_path, chunksize=chunksize):
        chunks_seen += 1
        chunk = chunk.rename(columns={c: canonical_for(c) for c in chunk.columns})
        if "Carrying_Value_000" not in chunk or "Classification" not in chunk:
            continue
        chunk["Carrying_Value_000"] = _num(chunk["Carrying_Value_000"])
        chunk["Bucket"] = chunk["Classification"].map(_CLASS_MAP).fillna(chunk["Classification"])
        rows_seen += len(chunk)
        if head_sample is None:
            head_sample = chunk.head(10).copy()
        for (bucket, cls), val in chunk.groupby(["Bucket", "Classification"])[
            "Carrying_Value_000"
        ].sum().items():
            if bucket in bucket_totals:
                bucket_totals[bucket] += float(val)
            detail[(bucket, cls)] = detail.get((bucket, cls), 0.0) + float(val)

    l1 = {b: bucket_totals[b] for b in _BUCKETS}
    l1["TOTAL"] = float(sum(l1[b] for b in _BUCKETS))

    l2 = pd.DataFrame(
        [{"Bucket": b, "Classification": c, "Carrying_Value_000_SAR000": v}
         for (b, c), v in sorted(detail.items())]
    )

    return CascadeResult(
        l1=l1,
        l2_classification=l2,
        l3_holdings=head_sample if head_sample is not None else pd.DataFrame(),
        l3_source=f"streamed large file ({rows_seen:,} rows in {chunks_seen} chunks)",
        l4_summary={},
        notes=[f"Large file processed in {chunks_seen} memory-bounded chunks "
               f"({rows_seen:,} holdings); sub-ledger shown is a sample of the first rows."],
        partial=False,
    )
