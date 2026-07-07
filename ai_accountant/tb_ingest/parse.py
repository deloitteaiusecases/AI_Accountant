"""Parse a TB grid into `ParsedTB` using a confirmed `ResolvedTBSchema` — TWO periods, bad-rows-surfaced.

Extracts current AND prior (the recon gap: a two-period TB needs both carried to the faces' comparative
columns). A row whose amount column has a value but no resolvable account identity is FLAGGED into
`bad_rows`, never silently dropped (the `face_tb/ingest.py:emit_account` discipline). No aggregation
here — each row becomes one engine `item`; the engine sums per concept after mapping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_accountant.tb_ingest.columns import _norm, heuristic_column_roles


@dataclass
class ParsedRow:
    account: str                  # account_code, or a synthesised row id when the TB carries no code column
    label: str                    # the best descriptor: verbatim mapping > label > deepest level > code
    current: float
    prior: "float | None"
    section: str = ""             # L0 (Assets / Liabilities / Equity / current-year result …) — for sign + close
    maturity_hint: str = ""       # L1 (Non-Current / Current …) — disambiguates split concepts
    levels: list = field(default_factory=list)
    source_row: int = -1
    source_tag: str = ""          # the OPTIONAL preparer note-routing tag (SL-1) — opaque, carried verbatim


@dataclass
class ParsedTB:
    rows: list = field(default_factory=list)
    bad_rows: list = field(default_factory=list)          # {row, reason} — surfaced, never dropped
    period_current: str = ""                              # the current/prior column HEADER text (e.g. "2024" /
    period_prior: str = ""                                # "2023") — carried to label the comparative columns


def _num(v):
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "nan", "None"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")           # accounting negatives: (1,234)
    s = s.strip("()").replace("SAR", "").replace("sar", "").strip()
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return 0.0


def detect_header_row(grid) -> int:
    """The header row scores highest on recognised column roles (mirrors face_tb/ingest's _score) — skips
    any title/notes block above the table. Looks only in the first 20 rows."""
    best_i, best_score = 0, -1
    for i in range(min(len(grid), 20)):
        roles = heuristic_column_roles(grid[i], grid[i + 1:i + 4])
        score = sum(1 for c in roles if c.role != "ignore")
        if score > best_score:
            best_i, best_score = i, score
    return best_i


def _cell(row, idx):
    return row[idx] if (idx is not None and idx < len(row)) else ""


def _txt(row, idx):
    v = _cell(row, idx)
    return "" if v is None else str(v).strip()


def parse_tb(grid, schema, *, header_row: "int | None" = None) -> ParsedTB:
    """Extract every data row below the header into a ParsedRow (current + prior), per the confirmed schema."""
    hdr = header_row if header_row is not None else detect_header_row(grid)
    out = ParsedTB()
    code_i, label_i, map_i = schema.code_index, schema.label_index, schema.mapping_index
    cur_i, pri_i, lvl_i = schema.current_index, schema.prior_index, schema.level_indices
    src_i = schema.source_index
    header_cells = grid[hdr] if hdr < len(grid) else []   # the year/period names live in the header row itself
    out.period_current = _txt(header_cells, cur_i)
    out.period_prior = _txt(header_cells, pri_i)
    for r in range(hdr + 1, len(grid)):
        row = grid[r]
        if not any(str(c).strip() for c in row):
            continue                                       # blank row
        code = re.sub(r"\s+", "", _txt(row, code_i)) if code_i is not None else ""
        levels = [_txt(row, i) for i in lvl_i]
        mapping = _txt(row, map_i)
        deepest_level = next((lv for lv in reversed(levels) if lv), "")
        label = mapping or _txt(row, label_i) or deepest_level or code
        has_amount = bool(_txt(row, cur_i)) or bool(_txt(row, pri_i))
        identity = code or label
        if not identity:
            if has_amount:                                 # an amount with no account → FLAG, never drop
                out.bad_rows.append({"row": r, "reason": "amount present but no resolvable account identity",
                                     "cells": [str(c) for c in row]})
            continue
        cur_v = _num(_cell(row, cur_i)) if cur_i is not None else 0.0
        pri_v = _num(_cell(row, pri_i)) if pri_i is not None else None
        if abs(cur_v) < 0.005 and (pri_v is None or abs(pri_v) < 0.005):
            continue                                       # zero in both periods (a section header / empty leaf)
        account = code or f"row{r}"
        out.rows.append(ParsedRow(
            account=account, label=label, current=cur_v, prior=pri_v,
            section=levels[0] if levels else "", maturity_hint=(levels[1] if len(levels) > 1 else ""),
            levels=levels, source_row=r, source_tag=_txt(row, src_i)))
    return out


def to_engine_inputs(parsed: ParsedTB):
    """ParsedTB → (items=[(account,label)], tb_rows=[{account,label,current,prior,section,maturity_hint}]).
    The extra section/maturity keys ride along for the sign + concept-resolver steps; build_master_fs_export
    reads only account/current/prior, so they are inert downstream."""
    items, tb_rows, seen = [], [], {}
    for row in parsed.rows:
        acct, n = row.account, seen.get(row.account, 0)
        seen[row.account] = n + 1
        if n:                                              # a repeated/non-unique code (or a level used as id)
            acct = f"{acct}#{n}"                           # → make it unique; the engine keys mappings by account
        items.append((acct, row.label))
        tb_rows.append({"account": acct, "label": row.label, "current": row.current,
                        "prior": row.prior, "section": row.section, "maturity_hint": row.maturity_hint,
                        "levels": list(row.levels), "source_tag": row.source_tag})
    return items, tb_rows
