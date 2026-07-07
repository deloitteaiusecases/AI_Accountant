"""Column-role proposer — the structure-agnostic heart (keys off MEANING, never position).

AI/heuristic PROPOSES each column's role (account_code / label / amount_current / amount_prior /
level / verbatim_mapping / ignore); a human CONFIRMS every column; code extracts. The deterministic
`heuristic_column_roles` covers the documented header patterns (year columns, GL/code, L0..Ln,
mapping) and is the offline path; `propose_column_roles` adds a pinned-LLM pass for headers the
heuristic can't place (the unfamiliar-layout interface). EITHER WAY the human confirm is the guard —
nothing is extracted on a guessed role. Mirrors the propose→confirm→apply shape of
`propose_account_concepts` / `propose_archetype`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ROLES = ("account_code", "label", "amount_current", "amount_prior", "level", "verbatim_mapping",
         "source_route", "adjustment", "ignore")
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")          # a 19xx/20xx year, even inside 'FY2024'
_LEVEL = re.compile(r"^(?:l|lvl|level)\s*([0-9])$")


@dataclass
class ColumnRole:
    index: int
    header: str
    role: str
    confidence: str           # high | medium | low
    evidence: str
    level_no: "int | None" = None     # for role == 'level'
    year: "int | None" = None         # for an amount column (drives current/prior ordering)


@dataclass
class ResolvedTBSchema:
    """The confirmed column→role map (the resolved schema for THIS upload)."""
    roles: list                                   # [ColumnRole] post-confirm
    headers: list = field(default_factory=list)

    def _idx(self, role):
        return next((c.index for c in self.roles if c.role == role), None)

    @property
    def code_index(self):
        return self._idx("account_code")

    @property
    def label_index(self):
        return self._idx("label")

    @property
    def mapping_index(self):
        return self._idx("verbatim_mapping")

    @property
    def current_index(self):
        return self._idx("amount_current")

    @property
    def prior_index(self):
        return self._idx("amount_prior")

    @property
    def level_indices(self):
        return [c.index for c in sorted((c for c in self.roles if c.role == "level"),
                                        key=lambda c: (c.level_no if c.level_no is not None else 99))]

    @property
    def has_mapping_column(self) -> bool:
        return self.mapping_index is not None or bool(self.level_indices)

    @property
    def adjustment_indices(self):
        return [c.index for c in self.roles if c.role == "adjustment"]

    @property
    def source_index(self):
        return self._idx("source_route")

    @property
    def period_ambiguous(self) -> bool:
        """Risk-1: the current/prior assignment was a POSITIONAL guess — two amount columns, NEITHER carrying
        a year to disambiguate (identical headers). A swap would still balance, so the build must force an
        explicit, values-shown human confirm; this flag is that signal."""
        cur = next((c for c in self.roles if c.role == "amount_current"), None)
        pri = next((c for c in self.roles if c.role == "amount_prior"), None)
        return cur is not None and pri is not None and cur.year is None and pri.year is None

    @property
    def period_current_label(self):
        c = next((c for c in self.roles if c.role == "amount_current"), None)
        return c.header if c else "Current"

    @property
    def period_prior_label(self):
        c = next((c for c in self.roles if c.role == "amount_prior"), None)
        return c.header if c else "Prior"

    @property
    def missing_required(self) -> list:
        miss = []
        if self.current_index is None:
            miss.append("amount_current")
        if self.code_index is None and self.label_index is None and not self.has_mapping_column:
            miss.append("an account identity (code / label / mapping / level)")
        return miss


def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def _looks_numeric(values) -> bool:
    seen = [v for v in values if str(v).strip() not in ("", "None")]
    if not seen:
        return False
    num = 0
    for v in seen:
        try:
            float(str(v).replace(",", ""))
            num += 1
        except ValueError:
            pass
    return num >= max(1, int(0.6 * len(seen)))


def heuristic_column_roles(headers, sample_rows) -> list:
    """Deterministic role proposal from header keywords + sample-cell shape. The documented offline path;
    also the fallback when the LLM proposer is unavailable. Amount columns are ranked current/prior by
    the year in their header (latest = current); a lone amount column is current."""
    cols = [str(h) if h is not None else "" for h in headers]
    samples = [[(r[i] if i < len(r) else "") for r in sample_rows] for i in range(len(cols))]
    out: list = []
    amounts: list = []                                     # (index, year|None) for ranking
    for i, raw in enumerate(cols):
        n = _norm(raw)
        ym = _YEAR.search(raw)
        year = int(ym.group(0)) if ym else None
        lm = _LEVEL.match(n)
        if "adjustment" in n or n in ("adj", "adj.", "adjustments"):
            # an ADJUSTMENT column (raw + adjustment = adjusted/Final) — recognised, never read as the amount.
            # Risk-1: marks the post-adjustment balance beside it as the preferred amount + drives the bridge.
            out.append(ColumnRole(i, raw, "adjustment", "high", "adjustment column (raw + adjustment = Final)"))
        elif year or any(k in n for k in ("amount", "balance", " sar", "sar ", "(sar", "value", "closing",
                                          "debit", "credit")) or (not n and _looks_numeric(samples[i])):
            out.append(ColumnRole(i, raw, "amount_current", "medium",
                                  f"period/amount header{' (year ' + str(year) + ')' if year else ''}", year=year))
            amounts.append((i, year))
        elif lm:
            out.append(ColumnRole(i, raw, "level", "high", f"hierarchy level L{lm.group(1)}",
                                  level_no=int(lm.group(1))))
        elif "source" in n or n in ("note", "note ref", "note reference", "ref", "routing", "note no"):
            # the OPTIONAL routing accelerator (SL-1): a preparer-declared note tag ("Note 13", "Note 15, 30").
            # Read as an OPAQUE proposal/cross-check signal — never matched against a note-name literal; the
            # build does NOT depend on it (concept→note routing works with this column absent).
            out.append(ColumnRole(i, raw, "source_route", "high", "preparer note-routing tag (optional hint)"))
        elif any(k in n for k in ("mapping", "fs line", "fs mapping", "actual mapping")):
            out.append(ColumnRole(i, raw, "verbatim_mapping", "high", "explicit mapping column"))
        elif any(k in n for k in ("description", "account name", "name", "label", "particular",
                                  "narration", "title")):
            out.append(ColumnRole(i, raw, "label", "high", "descriptive label header"))
        elif any(k in n for k in ("gl number", "gl account", "gl no", "account code", "account no",
                                  "natural account", "a/c", "account", "code", "gl")):
            out.append(ColumnRole(i, raw, "account_code", "high", "account/GL identifier header"))
        else:
            out.append(ColumnRole(i, raw, "ignore", "low", "no recognised role"))
    # RISK-1, prefer the ADJUSTED balance: a raw balance immediately BEFORE an adjustment column is the
    # pre-adjustment figure — the post-adjustment balance (after the adjustment) is the one to read. Demote
    # the raw one out of the amount pool (kept visible as 'ignore' with a loud reason, never silently dropped).
    adj_idx = {c.index for c in out if c.role == "adjustment"}
    if adj_idx:
        demoted = {i for (i, _y) in amounts if (i + 1) in adj_idx}     # raw = the balance just before an adjustment
        for c in out:
            if c.index in demoted and c.role == "amount_current":
                c.role, c.evidence = "ignore", "raw (pre-adjustment) balance — superseded by the adjusted column"
        amounts = [(i, y) for (i, y) in amounts if i not in demoted]
    # rank amount columns: latest year = current, the next = prior; ties/None keep grid order
    if amounts:
        ranked = sorted(amounts, key=lambda t: (t[1] is not None, t[1] or 0), reverse=True)
        cur_i = ranked[0][0]
        pri_i = ranked[1][0] if len(ranked) > 1 else None
        # RISK-1 period ambiguity: when neither candidate carries a YEAR, current-vs-prior is a POSITIONAL
        # guess (the headers are identical) — flag it LOW so the schema marks it period_ambiguous and the build
        # forces an explicit, values-shown human confirm (a silent swap would still balance, so the firewall
        # cannot catch it — the confirm is the only guard).
        ambiguous = ranked[0][1] is None and (pri_i is None or ranked[1][1] is None) and len(ranked) > 1
        for c in out:
            if c.role == "amount_current" and c.index != cur_i:
                c.role = "amount_prior" if c.index == pri_i else "ignore"
                c.evidence = ("earlier period → prior column" if c.index == pri_i
                              else "extra numeric column — left out (confirm if it is an amount)")
            if ambiguous and c.role in ("amount_current", "amount_prior") and c.index in (cur_i, pri_i):
                c.confidence = "low"
                c.evidence += " — PERIOD UNCONFIRMED: identical headers, current/prior assigned by position only"
    return out


# Generic column-role system prompt — the headers/samples are DATA in the user prompt, no layout literal.
_COLUMN_SYSTEM = (
    "You label the COLUMNS of an uploaded trial balance so a financial-statement generator can read it. "
    "You are given the column HEADERS and a few SAMPLE ROWS. For EACH column, assign exactly one role: "
    "account_code | label | amount_current | amount_prior | level | verbatim_mapping | ignore. Rules:\n"
    "1. Classify the column's ROLE only — do NOT compute, sum, or transform any amount.\n"
    "2. amount_current is the most recent period's figure column; amount_prior the comparative. A level "
    "column holds a hierarchy tag (L0..Ln / section). verbatim_mapping holds the financial-statement line "
    "the preparer already assigned. Use 'ignore' for anything else.\n"
    "3. Output EXACTLY one JSON object: {\"columns\":[{\"index\":int,\"role\":..,\"confidence\":"
    "\"high|medium|low\",\"evidence\":..}]}"
)


def propose_column_roles(headers, sample_rows, *, client=None) -> list:
    """Heuristic-first; for columns the heuristic leaves 'ignore' but that carry a header/content, ask the
    pinned LLM to place them (the unfamiliar-layout path). `client=None` → pure deterministic heuristic
    (the offline/test path). The human confirms every column afterwards regardless."""
    roles = heuristic_column_roles(headers, sample_rows)
    unplaced = [c for c in roles if c.role == "ignore" and str(c.header).strip()]
    if client is None or not unplaced:
        return roles
    rows = [[(r[i] if i < len(r) else "") for i in range(len(headers))] for r in sample_rows[:5]]
    prompt = ("Column headers (index: header):\n"
              + "\n".join(f"{i}: {h}" for i, h in enumerate(headers))
              + "\n\nSample rows:\n" + "\n".join(" | ".join(str(v) for v in r) for r in rows))
    raw = client.complete_json(prompt, system=_COLUMN_SYSTEM)
    by_idx = {int(c.get("index", -1)): c for c in raw.get("columns", []) if isinstance(c, dict)}
    for c in roles:
        p = by_idx.get(c.index)
        if c.role == "ignore" and p and p.get("role") in ROLES and p["role"] != "ignore":
            c.role, c.confidence, c.evidence = p["role"], str(p.get("confidence", "low")), str(p.get("evidence", "AI-proposed"))
    return roles


def column_amount_audit(schema, grid, *, header_row: int = 0, sample_n: int = 3) -> dict:
    """Risk-1 confirm payload: for the CHOSEN current/prior amount columns (and the raw + adjustment they
    derive from, if any), return the column header, its SUM over the data rows, and a few sample values — so
    the human (and a test) SEES which physical column became 'current' vs 'prior' and can catch a wrong/
    swapped pick BEFORE it silently ties. `period_ambiguous` echoes the schema flag; `swap_safe` is False
    when a global current/prior swap would NOT be caught arithmetically (always — see period_ambiguous)."""
    def _col(idx):
        if idx is None:
            return None
        vals = []
        for r in range(header_row + 1, len(grid)):
            cell = grid[r][idx] if idx < len(grid[r]) else None
            s = str(cell).strip().replace(",", "") if cell is not None else ""
            if s and s not in ("-", "None"):
                try:
                    vals.append(float(s.strip("()").replace("SAR", "").strip()) * (-1 if s.startswith("(") else 1))
                except ValueError:
                    pass
        hdr = str(grid[header_row][idx]) if header_row < len(grid) and idx < len(grid[header_row]) else ""
        return {"index": idx, "header": hdr, "sum": round(sum(vals), 2), "n": len(vals),
                "sample": vals[:sample_n]}
    return {"current": _col(schema.current_index), "prior": _col(schema.prior_index),
            "adjustments": [_col(i) for i in schema.adjustment_indices],
            "period_ambiguous": schema.period_ambiguous,
            "swap_safe": not schema.period_ambiguous}


def confirm_column_roles(roles, decisions=None) -> ResolvedTBSchema:
    """Apply human per-column overrides (index → role) and return the confirmed schema. A 'type your own'
    here picks a ROLE from the fixed enum — never a number."""
    decisions = decisions or {}
    confirmed = []
    for c in roles:
        role = decisions.get(c.index, c.role)
        confirmed.append(ColumnRole(c.index, c.header, role, c.confidence,
                                    c.evidence if role == c.role else "confirmed/overridden by reviewer",
                                    level_no=c.level_no, year=c.year))
    return ResolvedTBSchema(roles=confirmed, headers=[str(h) for h in roles and [c.header for c in roles]])
