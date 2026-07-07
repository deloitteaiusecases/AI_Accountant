"""Slice B2b/B2c — read the BALANCE-SHEET face sheet's current/non-current split (a SECOND sheet of the same
uploaded workbook) and resolve each line to a seed concept, so the engine can reconcile it against the
TB's lumped total and present the published split.

READ-EARLY / RESOLVE-LATE: the BS grid is read (and its columns confirmed) in the upload step, but the
RESOLVE here needs the seed `store` (which concept each line is), so it runs AFTER the archetype is
confirmed. Pure reuse of the TB machinery: the BS sheet is a `(label, amount)` grid that `parse_tb` reads.

RESOLUTION HIERARCHY (Slice B2c — deterministic-first → LIVE-AI-fallback → flag-floor, the established
shape): (1) `resolve_row` matches a clean "… — current/non-current" suffix/alias label to its `_nc`/`_c`
concept with NO model call (the Mobily path — free, deterministic); (2) a foreign label `resolve_row`
can't place is routed to the LIVE proposer (`propose_account_concepts`, the SAME one the TB account
mapping uses — labels only, no amounts, pinned model), accepted ONLY if it lands on a maturity-pair leaf
(decision H — an AI guess at a non-pair concept is off-task → flagged, never a silent no-op); (3) a line
NEITHER deterministic NOR the live AI can confidently place → `unmapped` (FLAGGED), never silently dropped.
With no client (no key) the AI never fires → the flag-floor catches it. The AI proposes the CONCEPT; the
engine's reconcile (nc+c == TB total, both years) still proves the AMOUNT afterward, and the human confirms.
NO amount is scaled — a different declared unit just fails the reconcile (never a silent conversion).
"""
from __future__ import annotations

from ai_accountant.tb_ingest.parse import parse_tb
from ai_accountant.tb_ingest.resolve import resolve_row


def parse_bs_split(grid, schema, store, *, client=None) -> dict:
    """Parse the confirmed BS-sheet grid and resolve each row to a seed concept (deterministic → live-AI → flag).

    Returns the provenanced carrier consumed by the engine's reconcile:
        {"source": "BS sheet",
         "amounts": {concept_id: {"current": float, "prior": float|None}},   # resolved, summed per concept
         "ai_proposed": [{"label", "concept_id"}],                           # LIVE-AI-proposed mapping (gate shows it)
         "unmapped": [{"label", "current", "prior", "reason"}]}              # FLAGGED, never applied"""
    parsed = parse_tb(grid, schema, header_row=None)
    amounts: dict = {}
    unmapped: list = []
    ai_proposed: list = []

    def _add(cid, row):
        cell = amounts.setdefault(cid, {"current": 0.0, "prior": None})
        cell["current"] = round((cell["current"] or 0.0) + row.current, 2)
        if row.prior is not None:
            cell["prior"] = round((cell["prior"] or 0.0) + row.prior, 2)

    pending = []                                             # rows deterministic resolution couldn't place
    for row in parsed.rows:
        rec = {"account": row.account, "label": row.label, "mapping": "",
               "maturity_hint": row.maturity_hint, "levels": list(row.levels)}
        concept, _matched = resolve_row(store, rec)
        if concept is not None:
            _add(concept.concept_id, row)                    # DETERMINISTIC — clean suffix/alias, NO model call
        else:
            pending.append(row)

    if pending and client is not None:                       # LIVE-AI-FALLBACK — same proposer the TB mapping uses
        from ai_accountant.master_fs.mapping import concept_for_label, propose_account_concepts
        clean, amb = store.maturity_pairs()
        pair_ids = ({i for p in clean for i in p}
                    | {i for a in amb for i in a.get("nc", []) + a.get("c", [])})   # the maturity-half leaves
        props = {p.code: p for p in
                 propose_account_concepts([(r.account, r.label) for r in pending], store, client=client)}
        for row in pending:
            p = props.get(row.account)
            c = concept_for_label(store, p.line) if (p and p.line) else None        # "unsure" → None → flag
            if c is not None and c.concept_id in pair_ids:   # decision H: a maturity-pair leaf ONLY
                _add(c.concept_id, row)
                ai_proposed.append({"label": row.label, "concept_id": c.concept_id})
            else:                                            # AI unsure OR off-pair → FLAG (never a silent no-op)
                unmapped.append({"label": row.label, "current": row.current, "prior": row.prior,
                                 "reason": "BS-sheet line not resolvable (deterministic + live AI both unsure / off-pair)"})
    else:
        for row in pending:                                  # no client (no key) → flag-floor, never canned output
            unmapped.append({"label": row.label, "current": row.current, "prior": row.prior,
                             "reason": "BS-sheet line not resolvable to a master concept"})

    return {"source": "BS sheet", "amounts": amounts, "ai_proposed": ai_proposed, "unmapped": unmapped}
