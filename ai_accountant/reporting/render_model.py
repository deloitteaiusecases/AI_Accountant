"""A render-target-agnostic view of a note: status + caveats + the figure rows.

Both the PDF and the Excel renderer consume this one structure, so any status detail that only lived
in the CLI renderer surfaces here before a second consumer exists. R11 is honoured: when the unit is
not confirmed, the figure is WITHHELD (None), not silently shown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_accountant.reporting.gap_report import note_status


@dataclass
class RenderRow:
    label: str
    value: float | None        # presented (scaled) CURRENT figure, or None when withheld (R11)
    raw_sar: float
    kind: str = "line"         # line | section | subtotal | total | movement | opening
    flag: str = ""             # ""|opening|source|reclass|control|magnitude
    indent: int = 0
    prior_value: float | None = None     # presented PRIOR-year figure (Slice S3b); None → no comparative column
    prior_raw_sar: float | None = None
    cells: list = field(default_factory=list)   # SL-1c.1 register-table: the row's VERBATIM attribute values, in
    #                                             `RenderableNote.columns` order. Empty for a label+amount note —
    #                                             the existing emitters ignore it (byte-identical).


@dataclass
class RenderableNote:
    note_ref: str
    status: str
    status_line: str
    caveats: list[str]
    reasons: list[str]
    unit_label: str
    unit_confirmed: bool
    rows: list[RenderRow] = field(default_factory=list)
    columns: list = field(default_factory=list)   # SL-1c.1: the register's attribute-column HEADERS (display
    #                                               order). Empty → a plain label+amount note (existing render).


def _flag_of(line) -> str:
    if getattr(line, "is_brought_forward", False):
        return "opening"
    if getattr(line, "needs_source", False):
        return "source"
    if getattr(line, "pending_reclassification", False):
        return "reclass"
    if getattr(line, "is_control_flag", False):
        return "control"
    return ""


def renderable(note) -> RenderableNote:
    ns = note_status(note)
    pres = note.presentation
    common = dict(note_ref=note.note_ref, status=ns.status, status_line=ns.headline,
                  caveats=ns.caveats, reasons=ns.reasons,
                  unit_label=pres.unit_label, unit_confirmed=pres.confirmed)
    rows: list[RenderRow] = []

    if hasattr(note, "total_nbv"):                                 # movement note (two-layer: cost + contra → NBV)
        clabel = getattr(note, "contra_label", "Accumulated contra")   # PP&E adapter → "Accumulated depreciation"

        def _pres(x):
            return note.presented(x) if pres.confirmed else None

        def _schedule(sched):                                      # the roll-forward detail (additive rows)
            rows.append(RenderRow("Opening", _pres(sched.opening), sched.opening, kind="line", indent=2))
            for ln, amt in sched.lines.items():
                rows.append(RenderRow(ln, _pres(amt), amt, kind="line", indent=2))

        for s in note.sections:
            rows.append(RenderRow(s.asset_class, _pres(s.nbv), s.nbv, kind="section"))
            _schedule(s.cost_movement)
            rows.append(RenderRow("  Cost", _pres(s.cost), s.cost, kind="line", indent=1))   # cost closing
            if s.has_contra:
                _schedule(s.contra_movement)
            rows.append(RenderRow("  " + clabel, _pres(s.contra_closing), s.contra_closing, kind="line", indent=1))
        rows.append(RenderRow("Total — net book value", _pres(note.total_nbv), note.total_nbv, kind="total",
                              flag="magnitude" if not note.magnitude_verified else ""))
    elif hasattr(note, "sections"):                                # Investments
        for s in note.sections:
            v = note.presented(s.net) if pres.confirmed else None
            rows.append(RenderRow(s.label, v, s.net, kind="section"))
            d = note.presented(s.net_split.dom) if pres.confirmed else None
            i = note.presented(s.net_split.intl) if pres.confirmed else None
            rows.append(RenderRow("  — Domestic", d, s.net_split.dom, kind="line", indent=1))
            rows.append(RenderRow("  — International", i, s.net_split.intl, kind="line", indent=1))
        tv = note.presented(note.total_net) if pres.confirmed else None
        rows.append(RenderRow("Total — Investments, net", tv, note.total_net, kind="total",
                              flag="magnitude" if not note.magnitude_verified else ""))
        ms = note.total_movement
        rows.append(RenderRow("Movement schedule", None, 0.0, kind="movement"))
        ov = note.presented(ms.opening) if pres.confirmed else None
        rows.append(RenderRow("  Opening balance", ov, ms.opening, kind="line", indent=1))
        for ln, amt in ms.lines.items():
            av = note.presented(amt) if pres.confirmed else None
            rows.append(RenderRow(f"  {ln}", av, amt, kind="line", indent=1))
        cv = note.presented(ms.closing) if pres.confirmed else None
        rows.append(RenderRow("  Closing balance", cv, ms.closing, kind="subtotal", indent=1))
    else:                                                          # Prepayments (and future flat notes)
        for line in note.lines:
            v = note.presented(line) if pres.confirmed else None
            rows.append(RenderRow(line.label, v, line.amount_sar, kind="line", flag=_flag_of(line)))
        tv = (round(note.account_total_sar / pres.scale, 2) if pres.confirmed else None)
        rows.append(RenderRow("Total", tv, note.account_total_sar, kind="total"))

    return RenderableNote(rows=rows, **common)


# ---- master-FS note statuses: colour (reinforcement) + LOUD WORDS (the primary signal) ---------------
# Hex strings so BOTH openpyxl (fgColor) and reportlab (HexColor) consume them. Status drives the colour;
# the WORD is always rendered too (a status must READ on B&W / a glance, not just shade).
STATUS_COLOUR = {
    "BUILT": "1E7A34", "RECONCILED": "1E7A34",                 # green — reconciles
    "PARTIAL": "B26A00", "SPLIT_UNCONFIRMED": "B26A00",        # amber — incomplete / unconfirmed
    "GROUPING_UNCONFIRMED": "B26A00",                          # amber — breakdown foots, grouping unreviewed
    "JUDGMENT_CONFIRMED": "6A1B9A", "JUDGMENT_UNCONFIRMED": "6A1B9A",   # purple — judgment, distinct from blocked
    "BLOCKED": "B00020",                                       # red — does not reconcile
    "not generated": "7A7A7A",                                 # grey — no GL / unsupported
}


def status_hex(status: str) -> str:
    return STATUS_COLOUR.get(status, "7A7A7A")


def status_caption(status: str, detail: str = "") -> str:
    """The LOUD text label that travels on the page next to the colour — never colour alone."""
    base = {
        "BUILT": "BUILT", "RECONCILED": "RECONCILED — reconciles to the TB",
        "PARTIAL": "PARTIAL — covered subtotal only",
        "SPLIT_UNCONFIRMED": "SPLIT — reconciles to TB but UNCONFIRMED (ai_assumed)",
        "GROUPING_UNCONFIRMED": "BREAKDOWN — foots to the line, but the grouping is UNREVIEWED",
        "JUDGMENT_CONFIRMED": "MANAGEMENT JUDGMENT — no independent verification (confirmed)",
        "JUDGMENT_UNCONFIRMED": "MANAGEMENT JUDGMENT — no independent verification (UNCONFIRMED)",
        "BLOCKED": "BLOCKED — does not reconcile",
        "not generated": "not generated",
    }.get(status, status)
    if not detail:
        return base
    sep = " — " if status == "not generated" else "; "
    return f"{base}{sep}{detail}"


def renderable_static(static_result: dict, *, unit_confirmed: bool = True) -> RenderableNote:
    """Render-target-agnostic view of a STATIC BREAKDOWN (Slice S2): TIERS (each a subtotal + its source leaf
    lines) and a grand total that STATES IT AGREES TO THE FACE LINE — the reader verifies the consolidation on
    the note page itself. A single-tier (tier=None) breakdown renders just the leaf lines + total. Rows carry
    real values; the consumer (screen / PDF) withholds them until the unit is confirmed."""
    status = static_result.get("status", "—")
    caption = static_result.get("caption", static_result.get("concept", "note"))
    tiers = static_result.get("tiers", [])
    has_prior = bool(static_result.get("has_prior"))          # a comparative column was supplied
    rows: list[RenderRow] = []

    def _has_tier(node):                                      # any tier ANYWHERE in the nesting (Slice S4)
        return bool(node.get("tier")) or any(_has_tier(ch) for ch in node.get("children", []))
    multi_tier = any(_has_tier(t) for t in tiers)
    leaf_indent = 2 if multi_tier else 1                      # leaves indent to 2 when any tier exists (the S2 layout;
    #                                                           the gap at indent 1 is filled by a tier-2 subtotal)

    def _emit(node, depth):                                   # subtotal at indent=depth; tier-2 nests one deeper
        if node.get("tier"):
            rows.append(RenderRow(node["tier"], node.get("subtotal"), node.get("subtotal", 0.0), kind="subtotal",
                                  indent=depth,
                                  prior_value=(node.get("subtotal_prior") if has_prior else None),
                                  prior_raw_sar=(node.get("subtotal_prior") if has_prior else None)))
        for line in node.get("lines", []):
            label, amt = line[0], line[1]
            pri = line[2] if len(line) > 2 else None
            rows.append(RenderRow(label, amt, amt, kind="line", indent=leaf_indent,
                                  prior_value=pri, prior_raw_sar=pri))
        for ch in node.get("children", []):
            _emit(ch, depth + 1)
    for t in tiers:
        _emit(t, 0)
    total = round(static_result.get("total", 0.0), 2)
    face = round(static_result.get("face_value", total), 2)
    total_pri = static_result.get("total_prior") if has_prior else None
    stmt = static_result.get("statement_title", "")
    tie = (f"Total — agrees to {caption} on the {stmt}" if stmt else f"Total — agrees to {caption}")
    rows.append(RenderRow(tie, total, total, kind="total", prior_value=total_pri, prior_raw_sar=total_pri))
    reasons = [msg for *_x, msg in static_result.get("findings", [])]
    caveats = [status_caption(status)]
    if abs(total - face) < 0.005:                             # the engine guarantee, stated for the reader
        caveats.append(f"Breakdown consolidates to {total:,.2f} — the {caption} face value.")
    if static_result.get("movement_caveat"):                  # omit-don't-zero: name the absent movement
        caveats.append(static_result["movement_caveat"])
    caveats += reasons
    return RenderableNote(note_ref=caption, status=status, status_line=status_caption(status),
                          caveats=caveats, reasons=reasons, unit_label="SAR",
                          unit_confirmed=unit_confirmed, rows=rows)


def renderable_register(register_result: dict, *, unit_confirmed: bool = True) -> RenderableNote:
    """Slice SL-1c.1 — render-target-agnostic view of a REGISTER-enriched note: an N-column TABLE carrying the
    register's per-row attribute values VERBATIM (`RenderRow.cells`, in `RenderableNote.columns` order) plus the
    amount column(s), grouped by the register's OWN section headers with a per-section sub-total, and a grand
    total that STATES IT AGREES TO THE FACE LINE (the tie the firewall proved). Column-LIST driven — carries
    WHATEVER attribute columns the register has, so a different-columns register renders with no code change."""
    status = register_result.get("status", "—")
    caption = register_result.get("caption", register_result.get("concept", "note"))
    columns = list(register_result.get("columns", []))
    has_prior = bool(register_result.get("has_prior"))
    rows: list[RenderRow] = []
    sections = register_result.get("sections", [])
    multi = len(sections) > 1
    for sec in sections:
        if sec.get("section") and multi:
            rows.append(RenderRow(sec["section"], None, 0.0, kind="section"))
        for r in sec.get("rows", []):
            pri = r.get("prior") if has_prior else None
            rows.append(RenderRow(r.get("label", ""), r.get("current", 0.0), r.get("current", 0.0),
                                  kind="line", indent=(1 if multi else 0), cells=list(r.get("cells", [])),
                                  prior_value=pri, prior_raw_sar=pri))
        if sec.get("section") and multi:
            rows.append(RenderRow(f"Sub-total — {sec['section']}", sec.get("subtotal"), sec.get("subtotal", 0.0),
                                  kind="subtotal", prior_value=(sec.get("subtotal_prior") if has_prior else None),
                                  prior_raw_sar=(sec.get("subtotal_prior") if has_prior else None)))
    total = round(register_result.get("total", 0.0), 2)
    face = round(register_result.get("face_value", total), 2)
    total_pri = register_result.get("total_prior") if has_prior else None
    stmt = register_result.get("statement_title", "")
    tie = (f"Total — agrees to {caption} on the {stmt}" if stmt else f"Total — agrees to {caption}")
    rows.append(RenderRow(tie, total, total, kind="total", prior_value=total_pri, prior_raw_sar=total_pri))
    reasons = [msg for *_x, msg in register_result.get("findings", [])]
    caveats = [status_caption(status)]
    if abs(total - face) < 0.005:
        caveats.append(f"Register of {sum(len(s.get('rows', [])) for s in sections)} line(s) reconciles to "
                       f"{total:,.2f} — the {caption} face value.")
    caveats += reasons
    return RenderableNote(note_ref=caption, status=status, status_line=status_caption(status),
                          caveats=caveats, reasons=reasons, unit_label="SAR", unit_confirmed=unit_confirmed,
                          rows=rows, columns=columns)


def renderable_split(split_result: dict, captions: dict) -> RenderableNote:
    """Render-target-agnostic view of a maturity SPLIT result (a dict, not a note object): the N-concept
    portion table, a Σ-check row, and the LOUD status + the persistent management-judgment caveat."""
    status = split_result.get("status", "—")
    concepts = split_result.get("split_concepts", [])
    portions = split_result.get("portions", {})
    note_ref = str(split_result.get("note", "split"))
    rows: list[RenderRow] = []
    for c in concepts:
        v = portions.get(c, 0.0)
        rows.append(RenderRow(captions.get(c, c), v, v, kind="line", indent=1))
    sigma = round(sum(portions.get(c, 0.0) for c in concepts), 2)
    rows.append(RenderRow("Σ split (must equal the note total)", sigma, sigma, kind="subtotal"))
    caveats = [status_caption(status)]
    if split_result.get("judgment_marker"):
        caveats.append(split_result["judgment_marker"])
    reasons = [msg for *_x, msg in split_result.get("findings", [])]
    return RenderableNote(note_ref=note_ref, status=status, status_line=f"{status} — {note_ref}",
                          caveats=caveats, reasons=reasons, unit_label="SAR", unit_confirmed=True, rows=rows)
