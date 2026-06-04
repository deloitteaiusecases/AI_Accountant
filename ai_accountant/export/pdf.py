"""PDF export (reportlab) of a computed Note 5 result.

Renders a clean, audit-style document: title, the L1 face, the L2 classification summary,
reconciliation (if an answer key was uploaded), and the confidence verdict + controls.
Takes a Note5Result (duck-typed) and returns the PDF as bytes.
"""
from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_HEADER_BG = colors.HexColor("#3B82F6")
_GRID = colors.HexColor("#CBD5E1")
_WARN = colors.HexColor("#FEF3C7")


def _fmt(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _table(data: list[list[str]], col_widths=None, highlight_status_col: int | None = None):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]
    if highlight_status_col is not None:
        for r in range(1, len(data)):
            if str(data[r][highlight_status_col]).upper() == "VARIANCE":
                style.append(("BACKGROUND", (0, r), (-1, r), _WARN))
    t.setStyle(TableStyle(style))
    return t


def export_to_pdf(result: Any) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="AI Accountant — Note 5",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("AI Accountant — Note 5: Investments, Net", styles["Title"]))
    story.append(Paragraph("All amounts SAR '000 · basis: IFRS 9 (policy rules applied when provided)",
                           styles["Normal"]))
    story.append(Spacer(1, 8))

    # L1 face
    l1 = result.cascade.l1
    story.append(Paragraph("Financial statement face (L1)", styles["Heading3"]))
    rows = [["Line", "Amount (SAR '000)"]]
    rows += [[b, _fmt(l1.get(b, 0.0))] for b in ["FVTPL", "FVOCI", "Amortised Cost", "TOTAL"]]
    story.append(_table(rows, col_widths=[90 * mm, 50 * mm]))
    story.append(Spacer(1, 10))

    # L2 classification summary
    l2 = result.cascade.l2_classification
    if l2 is not None and not l2.empty:
        story.append(Paragraph("Classification summary (L2)", styles["Heading3"]))
        head = list(l2.columns)
        body = [[_fmt(v) if str(c).endswith("000") or "000" in str(c) else str(v)
                 for c, v in zip(head, row)] for row in l2.itertuples(index=False)]
        story.append(_table([head] + body))
        story.append(Spacer(1, 10))

    # Reconciliation (only when an answer key was uploaded)
    recon_rows = [
        [s.level, ln.item, _fmt(ln.computed), _fmt(ln.expected), _fmt(ln.variance), ln.status]
        for s in (result.reconciliation_report or []) for ln in s.lines
    ]
    if recon_rows:
        story.append(Paragraph("Reconciliation vs stated financial statement", styles["Heading3"]))
        story.append(_table(
            [["Level", "Item", "Computed", "Expected", "Variance", "Status"]] + recon_rows,
            highlight_status_col=5,
        ))
        story.append(Spacer(1, 10))

    # Confidence
    conf = result.confidence
    if conf.controls:
        story.append(Paragraph(f"Confidence: {conf.level} "
                               f"({conf.passed}/{len(conf.controls)} controls passed)",
                               styles["Heading3"]))
        if result.confidence_narrative:
            story.append(Paragraph(result.confidence_narrative, styles["Normal"]))
            story.append(Spacer(1, 4))
        crows = [["Control", "Status"]] + [[c.name, c.status] for c in conf.controls]
        story.append(_table(crows, col_widths=[120 * mm, 25 * mm]))

    doc.build(story)
    return buf.getvalue()
