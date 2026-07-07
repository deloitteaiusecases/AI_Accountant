"""Slice SL-1c.1 — read a SUB-LEDGER REGISTER (e.g. the investment securities register) into a faithful-carry
payload: its rows + WHATEVER attribute columns it has, carried VERBATIM, with the amount column(s) identified
for the tie. The engine owns ONLY the amounts + the tie (downstream); attributes are pure pass-through.

THE COLUMN SPLIT (local heuristic — NEVER sends a value to a model): the amount column(s) are found by the
existing `heuristic_column_roles` (year-ranked → current/prior); EVERYTHING ELSE is an ATTRIBUTE carried in
display order (nothing is dropped — a register's 'ignore' columns are disclosure facts, not noise). A row with
text but no amount is a SECTION header ("A) HELD AT FVIS") that groups the rows beneath it. The AI, when it is
needed for an ambiguous amount header, sees HEADERS ONLY (`propose_register_amount_cols`) — never a row value.

No register-sheet or concept literal lives here: the caller supplies the grid; the concept association is the
seed `mechanism:"register"` + the proposed-confirmed sheet pick (`source_route`/`grid` precedent).
"""
from __future__ import annotations

from ai_accountant.tb_ingest.columns import _norm, heuristic_column_roles
from ai_accountant.tb_ingest.parse import _num, detect_header_row, _txt


_CLOSING = ("carrying", "closing", "nbv", "net book", "financing, net", "net 20", "balance")
_YEARRE = __import__("re").compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _amount_indices(headers, sample_rows, *, current_header=None, prior_header=None):
    """(current_idx, prior_idx) for the register's amount column(s). A confirmed header pair overrides. Else: among
    the heuristic's amount candidates, PREFER a closing/carrying column over an allowance/face/nominal sub-column
    (two columns can share a year — 'Carrying 2025' vs 'Allowance 2025' — so year-rank alone mis-picks), then rank
    current/prior by year. Header-shape only, never a value; an ambiguous pick is the AI-headers-only/confirm case."""
    norm = [_norm(h) for h in headers]
    if current_header is not None:
        cur = norm.index(_norm(current_header)) if _norm(current_header) in norm else None
        pri = norm.index(_norm(prior_header)) if (prior_header and _norm(prior_header) in norm) else None
        return cur, pri

    def _year(i):
        m = _YEARRE.search(headers[i])
        return int(m.group(0)) if m else -1
    # scan the HEADERS directly (not the heuristic's already-ranked roles, which keep only the top-2 amounts and
    # would drop a same-year carrying column): a candidate has a year OR an amount/closing keyword.
    cand = [i for i in range(len(headers))
            if _year(i) > 0 or any(k in norm[i] for k in _CLOSING + ("amount", "value", " sar", "(sar"))]
    closing = [i for i in cand if any(k in norm[i] for k in _CLOSING)]
    pool = sorted(closing or cand, key=_year, reverse=True)                # prefer carrying/closing over face/allowance
    cur = pool[0] if pool else None
    pri = next((i for i in pool[1:] if _year(i) != _year(pool[0])), None) if len(pool) > 1 else None
    return cur, pri


def read_register(grid, *, header_row=None, current_header=None, prior_header=None,
                  label_index=0) -> dict:
    """Grid → register payload (faithful-carry). Returns:
        {"columns":  [attribute header, …],                       # every non-amount column, display order
         "amount_current_header": str, "amount_prior_header": str|None,
         "rows": [{"label": str, "cells": [attr value, …], "current": float, "prior": float|None,
                   "section": str}],                              # one per DATA row, attributes VERBATIM
         "sections": [str, …]}                                    # section headers in order
    `label_index` is the column used as the row's display label (default the leftmost). A row with text but no
    amount becomes a SECTION header. Amounts are parsed; every other cell is carried as the source string."""
    hdr = header_row if header_row is not None else detect_header_row(grid)
    headers = [("" if c is None else str(c)) for c in grid[hdr]]
    sample = grid[hdr + 1:hdr + 6]
    cur_i, pri_i = _amount_indices(headers, sample, current_header=current_header, prior_header=prior_header)
    amount_idx = {i for i in (cur_i, pri_i) if i is not None}
    attr_idx = [i for i in range(len(headers)) if i not in amount_idx]      # EVERYTHING else → attributes
    columns = [headers[i] for i in attr_idx]
    hdr_norm = [_norm(h) for h in headers]
    # the FIRST section header can sit ABOVE the column-header row (a register lists 'A) …' then its columns) —
    # seed the initial section from the nearest single-label row in the title block above the header.
    section = ""
    for r in range(hdr - 1, -1, -1):
        cells_above = [_txt(grid[r], i) for i in range(len(headers))]
        nb = [c for c in cells_above if str(c).strip()]
        if len(nb) == 1:
            section = nb[0]
            break
    rows, sections = [], ([section] if section else [])
    for r in range(hdr + 1, len(grid)):
        row = grid[r]
        if not any(str(c).strip() for c in row):
            continue                                                       # blank
        if [_norm(_txt(row, i)) for i in range(len(headers))] == hdr_norm:
            continue                                                       # a REPEATED header row (per section) → skip
        cur_v = _num(row[cur_i]) if (cur_i is not None and cur_i < len(row)) else 0.0
        pri_v = _num(row[pri_i]) if (pri_i is not None and pri_i < len(row)) else None
        cells = [_txt(row, i) for i in attr_idx]
        nonblank = [c for c in cells if str(c).strip()]
        has_amount = abs(cur_v) >= 0.005 or (pri_v is not None and abs(pri_v) >= 0.005)
        if len(nonblank) <= 1 and not has_amount:                          # a single-label row → SECTION header
            section = nonblank[0] if nonblank else ""
            if section:
                sections.append(section)
            continue
        if not nonblank and not has_amount:
            continue
        # a DATA row — KEPT even at a zero carrying amount (a redeemed security is still a disclosure fact)
        rows.append({"label": _txt(row, label_index), "cells": cells, "current": cur_v,
                     "prior": pri_v, "section": section})
    return {"columns": columns, "amount_current_header": (headers[cur_i] if cur_i is not None else "Amount"),
            "amount_prior_header": (headers[pri_i] if pri_i is not None else None),
            "rows": rows, "sections": sections}


# Generic register-amount-header proposer — HEADERS ONLY (the faithful-carry firewall: a register's attribute
# VALUES, e.g. "Aa3"/"Stage 1", are regulated facts the model must NEVER see; only the headers reach it).
_AMOUNT_SYSTEM = (
    "You are given ONLY the column HEADERS of a sub-ledger register (no rows, no values). Identify which header "
    "is the CURRENT-period carrying/closing amount column and which is the PRIOR-period one. Rules:\n"
    "1. You see headers ONLY — never any cell value. Do not infer or invent a figure.\n"
    "2. Choose the closing/carrying amount (not a face/nominal value, not an allowance sub-column).\n"
    "3. Output EXACTLY one JSON object: {\"current\": <header or null>, \"prior\": <header or null>}"
)


def propose_register_amount_cols(headers, *, client=None) -> dict:
    """HEADERS-ONLY AI fallback for an ambiguous amount header (no rows sent). `client=None` → {} (the heuristic
    stands). The human confirms either way. The attribute-values-never-sent guard covers this payload."""
    if client is None:
        return {}
    raw = client.complete_json("Register column headers:\n" + "\n".join(f"- {h}" for h in headers),
                               system=_AMOUNT_SYSTEM)
    return {"current": raw.get("current"), "prior": raw.get("prior")}


_ASSOC_SYSTEM = (
    "You associate a sub-ledger REGISTER with the financial-statement concept it provides the detail for. You "
    "are given the register's column HEADERS (no rows, no values) and a list of candidate concepts (id + label). "
    "Pick the single concept this register details, or 'unsure'. Rules:\n"
    "1. You see HEADERS ONLY — never a cell value, never an amount.\n"
    "2. Choose EXACTLY one candidate id, or 'unsure' if the headers don't clearly indicate one.\n"
    "3. Output EXACTLY one JSON object: {\"concept_id\": <id or 'unsure'>, \"evidence\": <the header words used>}"
)


def propose_register_concept(sheet_name, headers, register_concepts, *, client=None) -> dict:
    """Layered sheet→concept association (SL-1c.1) — STRUCTURE only, never a value. `register_concepts` is the
    seed's register-declaring concepts as [(concept_id, label)]. LAYER 0 (deterministic): token-overlap of the
    SHEET NAME + HEADERS against each concept's label — a confident, unique winner resolves with NO model (the
    real 'Investment' sheet lands here; frozen-replay never calls the AI). LAYER 1 (live AI, headers-only): on a
    Layer-0 miss the model proposes from headers + the candidate labels. Either way the human confirms; unsure →
    None (flag). Returns {'concept_id', 'layer', 'evidence'}. No register/sheet/concept literal — candidates are
    seed data passed in."""
    import re

    def _toks(s):
        return {t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if len(t) > 3}
    hay = _toks(sheet_name)
    for h in (headers or []):
        hay |= _toks(h)

    def _score(label):                                         # a concept token HITS if it prefix-matches a
        return sum(1 for t in _toks(label)                     # haystack token (so 'investment'~'investments')
                   if any(t.startswith(h) or h.startswith(t) for h in hay))
    scored = sorted(((_score(lbl), cid) for cid, lbl in register_concepts), reverse=True)
    if scored and scored[0][0] >= 1 and (len(scored) == 1 or scored[0][0] > scored[1][0]):   # LAYER 0 — confident + unique
        return {"concept_id": scored[0][1], "layer": 0, "evidence": "sheet/header tokens match the concept label"}
    if client is None:                                          # offline / no key → flag (the human picks)
        return {"concept_id": None, "layer": 0, "evidence": "no confident deterministic match; no model available"}
    cand = "\n".join(f"- {cid}: {lbl}" for cid, lbl in register_concepts)   # LAYER 1 — AI, HEADERS ONLY
    raw = client.complete_json(f"Register sheet name: {sheet_name}\nColumn headers:\n"
                               + "\n".join(f"- {h}" for h in headers) + f"\n\nCandidate concepts:\n{cand}",
                               system=_ASSOC_SYSTEM)
    cid = raw.get("concept_id")
    valid = {c for c, _l in register_concepts}
    return {"concept_id": (cid if cid in valid else None), "layer": 1, "evidence": str(raw.get("evidence", ""))}
