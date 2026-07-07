"""The Property, plant & equipment note — a thin SPECIALISATION of the generic two-layer movement
mechanism (`movement.py`).

Relocated GL-free under master_fs (Slice 2). This module is PP&E's "seed": it supplies the caption, the
{Land} exemption, the depreciation movement configs, and adapter subclasses (`PPEClassSection`/`PPENote`)
that expose the PP&E field names (`accum_dep`, `is_land`, `missing_depreciation`, …) so the rendered page
reads in PP&E's own voice. The numbers are byte-identical to the generic mechanism: the mechanism role is
`accumulated_contra`, but the contra here IS depreciation.

Identification (account → asset_class, role) comes from a CONFIRMED structure (the AI proposes from the
LABEL, a human confirms); this module re-applies it deterministically — no account-code prefix map. Land
is not depreciated (a universal IFRS rule — a class with a cost account and no accumulated-depreciation
account is expected for Land; for any other class it is flagged).
"""
from __future__ import annotations

from ai_accountant.master_fs.notelib.movement import (ACCUM_CONTRA, COST, MovementNote, MovementSection,
                                                      build_movement_note)
from ai_accountant.master_fs.notelib.note import Presentation
from ai_accountant.master_fs.notelib.reference_codes import MovementConfig, PPE_COST_CONFIG, PPE_DEP_CONFIG

PPE_NOTE = "Property, plant and equipment"
ACCUM_DEP = ACCUM_CONTRA            # back-compat: PP&E's contra IS the mechanism contra role
_PPE_EXEMPT = frozenset({"land"})   # Land has a cost account and no accumulated depreciation (expected)


class PPEClassSection(MovementSection):
    """PP&E-named view of a generic `MovementSection`: the contra IS accumulated depreciation, the
    exemption IS Land. Old names are aliases over the generic fields (numbers identical)."""

    @property
    def accum_dep(self) -> float:                 # ≤ 0 (a contra) — alias of contra_closing
        return self.contra_closing

    @property
    def dep_movement(self):
        return self.contra_movement

    @property
    def dep_accounts(self) -> list:
        return self.contra_accounts

    @property
    def has_dep(self) -> bool:
        return self.has_contra

    @property
    def is_land(self) -> bool:                    # universal rule: land isn't depreciated
        return self.is_exempt

    @property
    def missing_depreciation(self) -> bool:
        """A depreciable class (not Land) with cost but no accumulated-depreciation account — flagged."""
        return self.missing_contra


class PPENote(MovementNote):
    """PP&E-named view of a generic `MovementNote` — `total_accum_dep` alias + PP&E's own voice for the
    provisional-reasons / status line (so the note pipeline reads "depreciation"/"Land"/"PP&E" verbatim)."""

    @property
    def total_accum_dep(self) -> float:
        return self.total_contra

    @property
    def contra_label(self) -> str:                # PP&E's contra IS accumulated depreciation (its voice)
        return "Accumulated depreciation"

    def provisional_reasons(self) -> list:
        reasons: list = []
        if not self.internal_structural_ties_ok:
            reasons.append("a structural tie failed (a cost or accumulated-depreciation schedule does "
                           "not roll forward to its closing)")
        for s in self.sections:
            if s.missing_depreciation:
                reasons.append(f"asset class {s.asset_class!r} has cost but no accumulated-depreciation "
                               f"account — unexpected for a depreciable class (only Land is exempt)")
        if self.unidentified_accounts:
            reasons.append(f"{len(self.unidentified_accounts)} PP&E account(s) without a confirmed "
                           f"class/role {self.unidentified_accounts} — flagged, not bucketed")
        if not self.presentation.confirmed:
            reasons.append("presentation unit/scale not confirmed (R11) — figures not yet presented")
        if self.unclassified_refs:
            reasons.append(f"unmapped reference code(s) {self.unclassified_refs} → 'Unclassified "
                           f"movement' (in closing, flagged)")
        if self.anchor is None:
            reasons.append(f"MAGNITUDE UNVERIFIED (R16): {self.magnitude_label}")
        elif not self.reconciles_to_tb:
            reasons.append(f"internally consistent but does NOT reconcile to the TB line "
                           f"(Δ = {self.anchor.gap:,.2f} TB-units) — reconciliation BLOCKS; internal "
                           f"consistency cannot upgrade it")
        elif not self.anchor.fully_covered:
            reasons.append(f"GL covers {self.anchor.coverage_pct}% of the TB line's leaves — reconciled "
                           f"to the covered subtotal")
        reasons.extend(self.upstream_reasons)
        return reasons

    def status_line(self) -> str:
        if not self.presentation.confirmed:
            return f"{self.status()} — PP&E (NBV) figure withheld until unit confirmed"
        val = round(self.total_nbv / self.presentation.scale, 2)
        return f"{self.status()} — PP&E, net book value {val:,.2f} {self.presentation.unit_label}"


def build_ppe_note(leaves: list, confirmed_structure: dict, anchor=None,
                   presentation: Presentation | None = None, resolved: set | None = None,
                   cost_config: MovementConfig = PPE_COST_CONFIG,
                   dep_config: MovementConfig = PPE_DEP_CONFIG) -> tuple:
    """PP&E specialisation of `build_movement_note`: the caption is "Property, plant and equipment", the
    exempt class is Land, the contra config is depreciation. Returns the generic note wrapped as a PP&E
    adapter (`PPENote`/`PPEClassSection`) so the note pipeline keeps the PP&E field names byte-identically.
    `leaves`/`confirmed_structure`: the PP&E roll-forward leaves + the confirmed (class, role) per account
    (role ∈ {cost, accumulated_contra}). Arithmetic only — never identifies a contra by a code pattern."""
    return build_movement_note(
        leaves, confirmed_structure, caption=PPE_NOTE, exempt_classes=_PPE_EXEMPT,
        cost_config=cost_config, contra_config=dep_config, anchor=anchor, presentation=presentation,
        resolved=resolved, section_cls=PPEClassSection, note_cls=PPENote)
