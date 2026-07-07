"""Render a client's FS against the master — populated leaves PLUS the deterministically-derived
net/subtotal/total spine, in section-blocked master order; comparatives from two TBs of the SAME client
(two periods). Amounts are summed and rolled up in code, never AI.

Render rules (the presentation-completeness fix):
  * leaf            — render iff populated (a mapped TB account summed into it), unchanged.
  * spine total     — kind=="total" (the 4 BS totals, Net income, Total CI): ALWAYS render.
  * net / subtotal  — render iff >=1 component present; a fully-empty intermediate hides (no "Fees,
                      net: 0" implying a real zero — same discipline as an empty leaf).
Section-blocked: sections in canonical order, leaves/intermediates by `order`, the section total last
(the authored order 999/1000 are end-of-section sentinels). `l1_group` is carried so the export can
emit the OCI two-bucket sub-headings.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_accountant.master_fs.derive import apply_carries, derive_statement

_EPS = 0.005


@dataclass
class RenderedLine:
    concept_id: str
    label: str                # the client's OWN wording for the concept (its alias), preserved
    section: str
    amount: float
    order: int
    derived: bool = False     # a computed net/subtotal/total (engine arithmetic), not a mapped leaf
    kind: str = "leaf"        # leaf | net | subtotal | total
    l1_group: "str | None" = None


@dataclass
class ComparativeLine:
    concept_id: str
    label: str
    section: str
    current: "float | None"
    prior: "float | None"
    derived: bool = False
    kind: str = "leaf"
    l1_group: "str | None" = None


def _amounts_by_concept(mapping_store, client_id, tb_amounts: dict) -> dict:
    """Sum each account's amount into its mapped concept. Unmapped accounts contribute to NOTHING —
    they are flagged in the mapping store, never silently folded into a line."""
    mapping = mapping_store.mapping(client_id)
    out: dict = {}
    for account, amt in tb_amounts.items():
        rec = mapping.get(account)
        if rec is None or rec.concept_id is None:
            continue
        out[rec.concept_id] = round(out.get(rec.concept_id, 0.0) + amt, 2)
    return out


def leaf_amounts(mapping_store, client_id, tb_amounts: dict) -> dict:
    """Public: {concept_id -> summed amount} for the LEAF concepts a TB populates (pre-derivation)."""
    return _amounts_by_concept(mapping_store, client_id, tb_amounts)


def carried_leaf_amounts(master_store, mapping_store, client_id, tb_amounts: dict) -> dict:
    """Leaf amounts WITH seed-declared carry-leaves populated (e.g. OCI net income from the P&L total)."""
    return apply_carries(master_store, _amounts_by_concept(mapping_store, client_id, tb_amounts))


def _ordered_concepts(master_store, statement) -> list:
    """Concepts in section-blocked order: sections in canonical order; within a section by `order`
    (so a section total at order 999/1000 lands at the foot of ITS section, not the statement)."""
    out = []
    for sec in master_store.sections(statement):
        out += sorted((c for c in master_store.statement(statement) if c.l0_section == sec),
                      key=lambda c: c.order)
    return out


def _label(master_store, concept, bank) -> str:
    return concept.label_for(bank) if bank else concept.canonical_concept


def apply_split_override(by_concept: dict, override_period: "dict | None") -> dict:
    """Layer a reconciled current/non-current split (Slice B2b) over the lumped leaf amounts: replace each
    overridden concept's amount with the BS-sheet figure. The TB amounts are NOT mutated — this returns a
    NEW map (the override is a presentation layer, the TB stays the reconcile anchor). `override_period` is
    {concept_id -> amount} already resolved for ONE period (current or prior); None → unchanged."""
    if not override_period:
        return by_concept
    return {**by_concept, **{cid: round(v, 2) for cid, v in override_period.items() if v is not None}}


def render_statement(master_store, mapping_store, client_id, tb_amounts, bank, statement,
                     *, split_override=None, sign_overrides=None) -> list:
    by_concept = apply_split_override(
        apply_carries(master_store, _amounts_by_concept(mapping_store, client_id, tb_amounts)), split_override)
    populated = {cid for cid, a in by_concept.items() if a is not None and abs(a) >= _EPS}
    if not populated:                                          # no ghost all-zero totals on an empty statement
        return []
    values, present = derive_statement(master_store, statement, by_concept, sign_overrides=sign_overrides)
    out = []
    for c in _ordered_concepts(master_store, statement):
        if c.is_computed:
            if c.kind != "total" and c.concept_id not in present:
                continue                                       # empty intermediate hides
            amt = values.get(c.concept_id, 0.0)
        else:
            if c.concept_id not in populated:
                continue                                       # empty leaf hides (unchanged)
            amt = by_concept[c.concept_id]
        out.append(RenderedLine(c.concept_id, _label(master_store, c, bank), c.l0_section, round(amt, 2),
                                c.order, derived=c.is_computed, kind=c.kind, l1_group=c.l1_group))
    return out


def render_master_fs(master_store, mapping_store, client_id, tb_amounts, bank=None) -> dict:
    return {st: render_statement(master_store, mapping_store, client_id, tb_amounts, bank, st)
            for st in master_store.statement_keys()}        # statement set is seed-declared


def render_comparative(master_store, mapping_store, client_id, tb_current, tb_prior, bank, statement,
                       *, split_override=None, sign_overrides=None) -> list:
    # split_override (Slice B2b): {concept_id -> {"current": x, "prior": y}} — one reconciled map fed to BOTH
    # periods (and reused by the engine's split-undetermined flag) so the face and the flag never diverge.
    # sign_overrides (Slice S6a): a per-TB component-sign correction, applied to BOTH periods' totals.
    cur_ov = {cid: o.get("current") for cid, o in (split_override or {}).items()}
    pri_ov = {cid: o.get("prior") for cid, o in (split_override or {}).items()}
    cur = {l.concept_id: l for l in render_statement(master_store, mapping_store, client_id, tb_current, bank,
                                                     statement, split_override=cur_ov, sign_overrides=sign_overrides)}
    pri = {l.concept_id: l for l in render_statement(master_store, mapping_store, client_id, tb_prior, bank,
                                                     statement, split_override=pri_ov, sign_overrides=sign_overrides)}
    ids = set(cur) | set(pri)
    out = []
    for c in _ordered_concepts(master_store, statement):       # union of either period, section-blocked order
        if c.concept_id not in ids:
            continue
        ref = cur.get(c.concept_id) or pri.get(c.concept_id)
        out.append(ComparativeLine(
            c.concept_id, ref.label, c.l0_section,
            current=cur[c.concept_id].amount if c.concept_id in cur else None,
            prior=pri[c.concept_id].amount if c.concept_id in pri else None,
            derived=c.is_computed, kind=c.kind, l1_group=c.l1_group))
    return out
