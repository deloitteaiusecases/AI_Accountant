"""Data loaders, including chunked/streamed reads for very large single-table CSVs (1M+ rows).

Large investment files are almost always ONE clean table (e.g. a million holdings or
transactions), not stacked multi-table sheets. For those we never load the whole file into
memory — we read it in row chunks and aggregate incrementally (see compute/streaming.py).
"""
from __future__ import annotations

import os
from typing import Any, Iterator

import pandas as pd

# Files larger than this are streamed rather than fully parsed in-memory.
LARGE_FILE_BYTES = 5_000_000  # ~5 MB


def file_size_bytes(file_or_path: Any) -> int:
    """Byte size of a path or an uploaded file-like object."""
    if isinstance(file_or_path, (str, os.PathLike)):
        return os.path.getsize(file_or_path)
    pos = file_or_path.tell()
    file_or_path.seek(0, os.SEEK_END)
    size = file_or_path.tell()
    file_or_path.seek(pos)
    return size


def is_large(file_or_path: Any, threshold: int = LARGE_FILE_BYTES) -> bool:
    try:
        return file_size_bytes(file_or_path) > threshold
    except Exception:  # noqa: BLE001
        return False


def first_line(file_or_path: Any) -> str:
    """Read just the header line (for cheaply checking a large file's columns)."""
    if isinstance(file_or_path, (str, os.PathLike)):
        with open(file_or_path, "r", encoding="utf-8-sig") as fh:
            return fh.readline()
    file_or_path.seek(0)
    raw = file_or_path.readline()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    file_or_path.seek(0)
    return raw


def iter_csv_chunks(file_or_path: Any, chunksize: int = 100_000) -> Iterator[pd.DataFrame]:
    """Yield a (single-table) CSV in row chunks, as string-typed DataFrames."""
    if not isinstance(file_or_path, (str, os.PathLike)):
        file_or_path.seek(0)
    for chunk in pd.read_csv(file_or_path, chunksize=chunksize, dtype=str):
        yield chunk.fillna("")
