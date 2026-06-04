"""Locate the Investments note inside the Bank AlJazira FS PDF and dump its text.

    python scripts/find_note5_in_pdf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import PyPDF2

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "baj_fs_q1_2025-english.pdf"


def main() -> None:
    # Windows consoles default to cp1252; FS text has unicode -> avoid crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    reader = PyPDF2.PdfReader(str(PDF))
    n = len(reader.pages)
    print(f"PDF pages: {n}")

    # Find pages whose text mentions investments in a note context.
    hits = []
    page_text = []
    for i, page in enumerate(reader.pages):
        txt = page.extract_text() or ""
        page_text.append(txt)
        low = txt.lower()
        if "investment" in low and ("fvtpl" in low or "fvoci" in low
                                    or "amortised cost" in low or "amortized cost" in low):
            hits.append(i)

    print(f"Candidate investment-note pages (0-indexed): {hits}")
    for i in hits[:6]:
        print("\n" + "=" * 80)
        print(f"PAGE {i}")
        print("=" * 80)
        print(page_text[i][:3500])


if __name__ == "__main__":
    main()
