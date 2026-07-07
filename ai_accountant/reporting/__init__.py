"""Reporting (Phase 5): the gap report + (later) Excel/PDF/UI renderers.

Every channel renders ONE honest model — status, the magnitude-unverified label, and the
provisional outlook are as prominent as the figures, never a footnote.
"""
from __future__ import annotations

from ai_accountant.reporting.gap_report import NoteStatus, note_status
from ai_accountant.reporting.render_model import RenderableNote, RenderRow, renderable
# Import the FUNCTIONS from their writer modules. The modules are named differently from the
# functions (excel_writer / pdf_writer) so importing a submodule can never rebind the function name
# on this package — the collision that made `export_excel` resolve to a module on the 2nd call.
from ai_accountant.reporting.excel_writer import export_excel
from ai_accountant.reporting.pdf_writer import export_pdf

__all__ = ["NoteStatus", "note_status", "RenderableNote", "RenderRow", "renderable",
           "export_excel", "export_pdf", "export_excel_bytes", "export_pdf_bytes"]


def export_pdf_bytes(notes) -> bytes:
    """In-memory PDF — for the browser download path (no server-side file)."""
    import io
    buf = io.BytesIO()
    export_pdf(notes, buf)
    return buf.getvalue()


def export_excel_bytes(notes) -> bytes:
    import io
    buf = io.BytesIO()
    export_excel(notes, buf)
    return buf.getvalue()
