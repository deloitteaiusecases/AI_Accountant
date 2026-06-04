"""Extract the investments accounting-policy text from the bundled Bank AlJazira FS PDF.

This is a REAL bank policy document we already have. We score each page by how much
investment-classification policy language it contains and save the best pages as a policy
sample (text) for testing the policy -> rules pipeline.

    python scripts/extract_policy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import PyPDF2

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "baj_fs_q1_2025-english.pdf"
OUT_DIR = ROOT / "policy_samples"
OUT_DIR.mkdir(exist_ok=True)

KEYWORDS = [
    "business model", "amortised cost", "amortized cost", "fair value through",
    "other comprehensive income", "classified", "classification", "sppi",
    "solely payments of principal", "held for trading", "fvis", "fvoci",
    "investments are", "investment securities",
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    reader = PyPDF2.PdfReader(str(PDF))
    scored = []
    for i, page in enumerate(reader.pages):
        txt = page.extract_text() or ""
        low = txt.lower()
        score = sum(low.count(k) for k in KEYWORDS)
        scored.append((score, i, txt))
    scored.sort(reverse=True)

    print("Top policy-relevant pages (page: score):")
    for score, i, _ in scored[:6]:
        print(f"  page {i}: {score}")

    best = [t for _, _, t in scored[:4] if t.strip()]
    out = OUT_DIR / "baj_investments_policy.txt"
    out.write_text("\n\n===== PAGE BREAK =====\n\n".join(best), encoding="utf-8")
    print(f"\nSaved {out} ({out.stat().st_size:,} bytes)")
    # Show a preview of the most relevant page.
    print("\n--- preview (best page) ---")
    print(scored[0][2][:1500])


if __name__ == "__main__":
    main()
