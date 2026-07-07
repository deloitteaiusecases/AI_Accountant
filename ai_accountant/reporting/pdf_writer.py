"""PDF export — the highest-stakes target: the artifact that leaves the system.

A PDF outlives its context, so the prominence principle must survive INSIDE the file: every page
carries a red "NOT FINAL" footer stamp, and the provisional/magnitude caveat is rendered both in a
banner above the figures AND inline on the total row — so a page printed or screenshotted on its own
still says it is provisional. There is no clean path that drops the caveats.
"""
from __future__ import annotations

from functools import partial

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from ai_accountant.reporting.render_model import renderable

_RED = colors.HexColor("#B00020")
_GREY = colors.HexColor("#EEEEEE")


def _fmt(value, raw):
    if value is None:
        return "WITHHELD (unit unconfirmed)"
    return f"{value:,.2f}"


def _doc_stamp(rnotes) -> str:
    # A document-level warning (the per-note caveat lives in each note's banner + total row).
    bits = []
    if any(n.status != "BUILT" for n in rnotes):
        bits.append("NOT FINAL — PARTIAL/BLOCKED notes present")
    if any("MAGNITUDE UNVERIFIED" in c for n in rnotes for c in n.caveats):
        bits.append("MAGNITUDE-UNVERIFIED NOTES PRESENT")
    return "DRAFT — " + " — ".join(bits) if bits else "DRAFT"


def _footer(canvas, doc, stamp: str):
    canvas.saveState()
    w, _h = A4
    canvas.setFillColor(_RED)
    canvas.rect(0, 0, w, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(10 * mm, 4.5 * mm, stamp[:130])
    canvas.drawRightString(w - 10 * mm, 4.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def export_pdf(notes: list, path: str) -> str:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14)
    banner = ParagraphStyle("banner", parent=styles["Normal"], textColor=colors.white,
                            fontName="Helvetica-Bold", fontSize=10, leading=13)
    rnotes = [renderable(n) for n in notes]
    stamp = _doc_stamp(rnotes)

    story = [Paragraph("Financial Statements — Notes (DRAFT)", h1),
             Paragraph("Every page is stamped NOT FINAL while any note is provisional.",
                       styles["Italic"]), Spacer(1, 6 * mm)]

    for rn in rnotes:
        story.append(Paragraph(rn.note_ref, h1))
        # prominent status banner ABOVE the figures
        banner_lines = [f">> STATUS: {rn.status}" + ("  (NOT FINAL)" if rn.status != "BUILT" else ""),
                        rn.status_line] + [f"!! {c}" for c in rn.caveats]
        btxt = "<br/>".join(_esc(x) for x in banner_lines)
        bt = Table([[Paragraph(btxt, banner)]], colWidths=[170 * mm])
        bt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _RED),
                                ("BOX", (0, 0), (-1, -1), 1, _RED),
                                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                ("TOPPADDING", (0, 0), (-1, -1), 6),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(bt)
        story.append(Spacer(1, 4 * mm))

        # figures table; the TOTAL row carries the status caveat INLINE
        data = [["", f"Amount ({rn.unit_label})"]]
        stys = []
        for i, r in enumerate(rn.rows, start=1):
            label = ("    " * r.indent) + r.label
            if r.flag:
                label += f"   [{r.flag.upper()}]"
            if r.kind == "total":
                tag = "  — NOT FINAL" if rn.status != "BUILT" else ""
                mag = "  [MAGNITUDE UNVERIFIED]" if r.flag == "magnitude" else ""
                label = f"{r.label}{mag}{tag}"
                stys += [("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                         ("LINEABOVE", (0, i), (-1, i), 1, colors.black),
                         ("TEXTCOLOR", (0, i), (-1, i), _RED if rn.status != "BUILT" else colors.black)]
            elif r.kind in ("section", "movement"):
                stys.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            data.append([label, _fmt(r.value, r.raw_sar) if r.kind not in ("movement",) else ""])
        t = Table(data, colWidths=[120 * mm, 50 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), _GREY),
                               ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                               ("FONTSIZE", (0, 0), (-1, -1), 9),
                               *stys]))
        story.append(t)
        story.append(PageBreak())

    doc = SimpleDocTemplate(path, pagesize=A4, bottomMargin=20 * mm)
    foot = partial(_footer, stamp=stamp)
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return path


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
