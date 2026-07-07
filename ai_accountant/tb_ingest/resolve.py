"""Deterministic preparer-path resolvers for a TB that already carries its mapping (a level/mapping
column, e.g. TB_Test's L0/L1/L2). PREPARER-first, AI-fallback (the agreed decision): when the verbatim
mapping exact-matches a seed concept it is resolved deterministically (no LLM, still human-confirmed in
G2); only labels that DON'T resolve fall to the live `propose_account_concepts`. Split concepts
(current vs non-current) are disambiguated by the row's maturity hint (L1), never guessed.

These return the SAME shapes the existing chain consumes — `FaceMappingProposal` (for the G2 confirm)
and `ArchetypeProposal` (for the G1 confirm) — so nothing downstream changes.
"""
from __future__ import annotations

import re

from ai_accountant.master_fs.notelib.propose import FaceMappingProposal
from ai_accountant.master_fs.detect import ArchetypeProposal, ArchetypeRanking
from ai_accountant.master_fs.seed import load_detect_thresholds, load_registry


def _norm(s) -> str:
    # normalise dash variants and the mojibake replacement char to a plain hyphen so an en-dash / encoding
    # mishap in an uploaded label still matches the seed's hyphen ("Cash flow hedge - change in fair value")
    t = re.sub(r"[‐-―−�]", "-", str(s or ""))
    return re.sub(r"\s+", " ", t.strip()).lower()


def _is_non_current(concept) -> bool:
    return ("non" in concept.l0_section.lower() and "current" in concept.l0_section.lower()) \
        or "non-current" in concept.canonical_concept.lower()


def _statement_from_levels(levels) -> str:
    """Which statement a row belongs to, from its hierarchy levels (the same caption can sit on the BS and
    the P&L, e.g. 'Zakat and income tax' — payable vs charge)."""
    joined = " ".join(str(lv) for lv in levels).lower()
    l0 = _norm(levels[0]) if levels else ""                  # the section tag (Assets/Liability/Equity/Income/Expense)
    # L0 IS AUTHORITATIVE when present: a balance-sheet section stays the balance sheet even if a reserve is named
    # "…OCI…" (e.g. an equity 'Share in OCI of an associate' reserve, or a 'FVOCI' investment) — only INCOME/EXPENSE
    # rows are sub-classified into the income statement vs OCI.
    if l0 in ("assets", "asset", "liability", "liabilities", "equity"):
        return "balance_sheet"
    is_oci = "comprehensive" in joined or re.search(r"\boci\b", joined)   # 'oci' the WORD, not inside 'FVOCI'
    if l0 in ("income", "expense", "revenue", "expenses"):
        return "comprehensive_income" if is_oci else "income_statement"
    if is_oci:
        return "comprehensive_income"
    if "current year" in joined or "current-year" in joined or "p&l" in joined \
            or "profit or loss" in joined or "profit and loss" in joined or "income statement" in joined:
        return "income_statement"
    return "balance_sheet"


def resolve_concept(store, label, maturity_hint="", *, statement_hint="", levels=None):
    """Match a verbatim label to ONE seed leaf concept (canonical or alias). Disambiguate a label shared
    by several concepts: first by STATEMENT (the row's section — a BS payable vs a P&L charge), then by
    MATURITY (a current/non-current split). Still ambiguous → None (flag, never force-map)."""
    n = _norm(label)
    if not n:
        return None
    matches = [c for c in store.concepts.values() if c.kind == "leaf"          # LAYER 0 — exact (UNCHANGED)
               and (_norm(c.canonical_concept) == n or any(_norm(v) == n for v in c.label_aliases.values()))]
    if not matches:
        # LAYER 1 (Slice S5a-resolve) — retry after stripping generic qualifiers (", net"/parenthetical), fired
        # ONLY on a Layer-0 miss so a suffix-variant label ("Investments" → "Investments, net") maps WITHOUT the
        # live AI. Builds matches as a LIST → the existing statement/maturity disambiguation below still runs, so a
        # strip-COLLISION routes through it to None (never a guessed pick). Bounded equality, NOT containment; the
        # maturity suffix survives, so a bare label can't strip-match a current/non-current concept.
        from ai_accountant.master_fs.notes import _strip_quals
        sn = _strip_quals(n)
        matches = [c for c in store.concepts.values() if c.kind == "leaf"
                   and (_strip_quals(_norm(c.canonical_concept)) == sn
                        or any(_strip_quals(_norm(v)) == sn for v in c.label_aliases.values()))]
    if not matches:
        return None
    # STATEMENT filter FIRST (SL-1b cross-statement guard): a row's concept must live in the row's own statement.
    # Applied even to a LONE match — else a P&L row whose instrument label ("Financing", "Customers' deposits")
    # uniquely matches a BS concept's alias mis-routes onto the balance sheet (inflating it). A lone match in the
    # WRONG statement → None (resolve_row then tries the row's other levels, or it flags) — never a cross-statement map.
    stmt = statement_hint or (_statement_from_levels(levels) if levels else "")
    if stmt:
        by_stmt = [c for c in matches if c.statement == stmt]
        if by_stmt:
            matches = by_stmt
        elif len(matches) == 1:
            return None
    if len(matches) == 1:
        return matches[0]
    # split pair — pick a side ONLY on a GENUINE maturity signal ('current' appears in the hint, which both
    # 'Current …' and 'Non-Current …' carry). A blank/ambiguous hint is UNDETERMINED → None (never a silent
    # default to current/non-current); the build-time pair guard then surfaces it.
    h = maturity_hint.lower()
    if "current" not in h:
        return None
    want_nc = "non" in h
    picked = [c for c in matches if _is_non_current(c) == want_nc]
    return picked[0] if len(picked) == 1 else None         # still ambiguous → None


def resolve_row(store, row):
    """Resolve ONE TB row to a seed concept by scanning its descriptors — the explicit mapping/label and
    EACH hierarchy level — and taking the value that matches a leaf concept (a section/sub-account name
    won't match a leaf; only the FS-line level does). Returns (concept | None, matched_label).

    COMBINED-KEY fallback (SL-1b): tried LAST, only after every single descriptor misses — an adjacent
    "L_outer - L_inner" pair (e.g. 'Fair value reserve - FVOCI debt - Net change in fair value'). Needed
    where the leaf level alone is AMBIGUOUS ('Net change in fair value' sits under both FVOCI-debt and
    FVOCI-equity, disambiguated only by the reserve above it). The router stays untouched — this only adds
    more candidate strings; a combined key that matches no alias still resolves to None (flag), never forced."""
    hint = row.get("maturity_hint", "")
    levels = [lv for lv in row.get("levels", [])]
    nonblank = [lv for lv in levels if str(lv).strip()]
    combined = [f"{a} - {b}" for a, b in zip(nonblank, nonblank[1:])]    # adjacent "outer - inner" pairs
    for v in [row.get("label", ""), row.get("mapping", "")] + levels + combined:
        c = resolve_concept(store, v, hint, levels=levels)
        if c is not None:
            return c, v
    return None, ""


def build_upload_proposals(tb_rows, store, *, client=None) -> list:
    """One mapping proposal per row: preparer exact-match first (deterministic), live AI for the rest.
    Returns FaceMappingProposal objects in row order, for the existing per-line G2 confirm."""
    from ai_accountant.master_fs.mapping import propose_account_concepts
    out, ai_items = [], []
    for r in tb_rows:
        concept, matched = resolve_row(store, r)
        if concept is not None:
            out.append(FaceMappingProposal(code=r["account"], label=r.get("label", ""),
                                           line=concept.canonical_concept, confidence="high",
                                           evidence=f"preparer mapping — '{matched}' matches this concept"))
        else:
            ai_items.append((r["account"], r.get("label", "")))
            out.append(None)                               # placeholder, filled below (preserves order)
    if ai_items:
        ai = {p.code: p for p in propose_account_concepts(ai_items, store, client=client)}
        out = [p if p is not None else ai.get(tb_rows[i]["account"]) for i, p in enumerate(out)]
    return [p for p in out if p is not None]


def propose_archetype_from_mapping(tb_rows, stores):
    """Deterministic archetype proposal when the TB carries a mapping the engine can resolve: score each
    registered seed by the fraction of rows whose verbatim mapping resolves to one of its concepts. A
    clear winner → an ArchetypeProposal(verdict='propose'); otherwise None (caller falls back to the live
    `propose_archetype`). Still human-confirmed in G1 — this only pre-fills the pick."""
    reg = load_registry()
    n = max(len(tb_rows), 1)
    ranked = []
    for sid, store in stores.items():
        hits = [(r.get("label", ""), "") for r in tb_rows if resolve_row(store, r)[0] is not None]
        ranked.append(ArchetypeRanking(seed_id=sid, label=(reg.get(sid, {}) or {}).get("label", sid),
                                       score=round(len(hits) / n, 4), matched=hits[:6], absent=[]))
    ranked.sort(key=lambda r: r.score, reverse=True)
    if not ranked:
        return None
    th = load_detect_thresholds()
    s1 = ranked[0].score
    s2 = ranked[1].score if len(ranked) > 1 else 0.0
    if s1 >= max(th["floor"], 0.5) and (s1 - s2) >= th["margin"]:
        return ArchetypeProposal(verdict="propose", seed_id=ranked[0].seed_id, ranked=ranked)
    return None                                            # not clear from the mapping → use the live detector
