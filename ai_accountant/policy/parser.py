"""Extract raw text from an uploaded accounting-policy document (PDF/TXT).

Migrated from the old engine.py.
"""
from __future__ import annotations

from typing import Any

import PyPDF2


def parse_policy_document(uploaded_file: Any) -> str:
    """Return the plain text of a policy PDF/TXT, or an error string on failure."""
    filename = uploaded_file.name
    uploaded_file.seek(0)
    try:
        if filename.lower().endswith(".pdf"):
            reader = PyPDF2.PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
        if filename.lower().endswith(".txt"):
            return uploaded_file.read().decode("utf-8")
        return "Unsupported policy file format. Please upload PDF or TXT."
    except Exception as exc:  # noqa: BLE001
        return f"Error extracting text: {exc}"
