"""Generic two-layer roll-forward / movement note — the MECHANISM behind every cost-plus-contra
movement note (a fixed-asset roll-forward, an intangible-asset roll-forward, a right-of-use schedule,
and so on; each specific note supplies its own vocabulary, this module supplies none).

Relocated GL-free under master_fs (Slice 2). The former GL coupling — the `clarify` ClarificationQueue —
was only ever used to RAISE questions the seed engine then discarded (it consumes `build_movement_note(...)[0]`
and throws the queue away). So the queue machinery is dropped here; the builder returns `(note, None)` to
keep the tuple-indexing contract. `MovementSchedule` (formerly in fs_notes/investments) is carried inline.

A movement note is a TWO-LAYER schedule: a cost roll-forward (opening + additions − disposals ±
adjustments → closing cost) and a CONTRA roll-forward (opening + contra charge − disposals → closing
contra), netting to net book value (NBV = cost + contra, the contra being negative), per class and in
total. This builder carries NO note-specific vocabulary — caption, the contra's name, the movement-line
names, and the exempt classes ALL arrive as params/config. Identification (account → class, role) comes
from a CONFIRMED structure (AI proposes the label, a human confirms); the netting is deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_accountant.master_fs.notelib.note import Presentation
from ai_accountant.master_fs.notelib.reference_codes import MovementConfig

COST = "cost"
ACCUM_CONTRA = "accumulated_contra"          # the MECHANISM contra role (not a charge name)
_MAGNITUDE_LABEL = "internally consistent; magnitude unverified — no anchoring TB line"


@dataclass
class MovementSchedule:
    opening: float = 0.0
    lines: dict[str, float] = field(default_factory=dict)   # line label → amount
    closing: float = 0.0

    @property
    def computed_closing(self) -> float:
        return round(self.opening + sum(self.lines.values()), 2)

    @property
    def ties(self) -> bool:
        return abs(self.computed_closing - self.closing) < 0.005


def _build_schedule(leaves: list, config: MovementConfig) -> tuple:
    """Roll one role's leaves into a movement schedule via the PER-NOTE config. Returns
    (schedule, unmapped_refs). Opening rows (OPEN-BF) are already in leaf.opening, never a movement."""
    sched = MovementSchedule()
    unmapped: set = set()
    for leaf in leaves:
        sched.opening = round(sched.opening + leaf.opening, 2)
        sched.closing = round(sched.closing + leaf.closing, 2)
        for ref, amt in leaf.movement_by_ref.items():
            line, mapped = config.classify(ref)
            if not mapped:
                unmapped.add(ref or "(blank)")
            sched.lines[line] = round(sched.lines.get(line, 0.0) + amt, 2)
    sched.lines = {ln: sched.lines[ln] for ln in config.ordered_lines if ln in sched.lines}
    return sched, unmapped


@dataclass
class MovementSection:
    asset_class: str
    cost_movement: MovementSchedule
    contra_movement: MovementSchedule
    cost_accounts: list = field(default_factory=list)
    contra_accounts: list = field(default_factory=list)
    exempt_classes: frozenset = frozenset()

    @property
    def cost(self) -> float:
        return self.cost_movement.closing

    @property
    def contra_closing(self) -> float:            # ≤ 0 (a contra)
        return self.contra_movement.closing

    @property
    def nbv(self) -> float:
        return round(self.cost + self.contra_closing, 2)

    @property
    def has_contra(self) -> bool:
        return bool(self.contra_accounts)

    @property
    def is_exempt(self) -> bool:                   # a class declared (by config) to have no contra
        return self.asset_class.strip().lower() in self.exempt_classes

    @property
    def schedules_tie(self) -> bool:
        return self.cost_movement.ties and self.contra_movement.ties

    @property
    def missing_contra(self) -> bool:
        """A non-exempt class with cost but no accumulated-contra account — flagged."""
        return self.cost != 0 and not self.has_contra and not self.is_exempt


@dataclass
class MovementNote:
    note_ref: str                                  # the note CAPTION (injected; not a fixed string)
    sections: list
    presentation: Presentation
    anchor: object = None                          # the TB line's LineRecon (slice-5 contract)
    upstream_status: str = "BUILT"
    upstream_reasons: list = field(default_factory=list)
    unclassified_refs: list = field(default_factory=list)
    unidentified_accounts: list = field(default_factory=list)   # no confirmed structure — flagged
    magnitude_label: str = _MAGNITUDE_LABEL
    resolved: set = field(default_factory=set)

    @property
    def total_cost(self) -> float:
        return round(sum(s.cost for s in self.sections), 2)

    @property
    def total_contra(self) -> float:
        return round(sum(s.contra_closing for s in self.sections), 2)

    @property
    def total_nbv(self) -> float:
        return round(sum(s.nbv for s in self.sections), 2)

    @property
    def nbv_by_class(self) -> dict:
        return {s.asset_class: s.nbv for s in self.sections}

    @property
    def contra_label(self) -> str:
        """The display label for the contra layer. Generic at the mechanism level; a specific note (PP&E)
        overrides it in its adapter so the rendered page reads in that note's own voice."""
        return "Accumulated contra"

    @property
    def internal_structural_ties_ok(self) -> bool:
        """STRUCTURAL: both schedules tie per class, and per-class NBV = cost + contra. A precondition,
        NOT the authority — internal consistency can be perfect and still disagree with the TB line."""
        return all(s.schedules_tie for s in self.sections)

    @property
    def reconciles_to_tb(self) -> bool:
        return self.anchor is not None and self.anchor.reconciles

    @property
    def magnitude_verified(self) -> bool:
        return self.reconciles_to_tb

    @property
    def tie_ok(self) -> bool:
        """FLIPPED contract (slice 5): NBV reconciles to the TB line AND the schedules tie. No anchor
        → False (magnitude-unverified, never silently True)."""
        return self.reconciles_to_tb and self.internal_structural_ties_ok

    def provisional_reasons(self) -> list:
        reasons: list = []
        if not self.internal_structural_ties_ok:
            reasons.append("a structural tie failed (a cost or accumulated-contra schedule does not "
                           "roll forward to its closing)")
        for s in self.sections:
            if s.missing_contra:
                reasons.append(f"class {s.asset_class!r} has a cost balance but no accumulated-contra "
                               f"account — unexpected for a non-exempt class")
        if self.unidentified_accounts:
            reasons.append(f"{len(self.unidentified_accounts)} account(s) without a confirmed class/role "
                           f"{self.unidentified_accounts} — flagged, not bucketed")
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

    def status(self) -> str:
        """A reconciliation BLOCK (internally consistent but ≠ TB line) overrides everything."""
        if self.anchor is not None and self.anchor.status() == "BLOCKED":
            return "BLOCKED"
        return "BUILT" if not self.provisional_reasons() else "PARTIAL"

    def status_line(self) -> str:
        if not self.presentation.confirmed:
            return f"{self.status()} — {self.note_ref} (NBV) figure withheld until unit confirmed"
        val = round(self.total_nbv / self.presentation.scale, 2)
        return f"{self.status()} — {self.note_ref}, net book value {val:,.2f} {self.presentation.unit_label}"

    def presented(self, value):
        if value is None or not self.presentation.confirmed:
            return None
        return round(value / self.presentation.scale, 2)


def build_movement_note(leaves: list, confirmed_structure: dict, *, caption: str,
                        exempt_classes=frozenset(), cost_config: MovementConfig,
                        contra_config: MovementConfig, cost_role: str = COST,
                        contra_role: str = ACCUM_CONTRA, anchor=None,
                        presentation: Presentation | None = None, resolved: set | None = None,
                        section_cls=MovementSection, note_cls=MovementNote) -> tuple:
    """Build a two-layer movement note (cost layer + contra layer → NBV, by class) from `leaves` and a
    CONFIRMED structure (account → class/role). The builder does only ARITHMETIC over that confirmed
    structure; it never identifies a contra by a code pattern, and it names no note-specific vocabulary —
    `caption`, `exempt_classes`, the configs, and the role strings all arrive from the caller. Returns
    `(note, None)`: the second slot was a discarded clarification queue (removed with the GL pipeline).

    `section_cls`/`note_cls` let a specific note inject adapter subclasses that expose its own field
    names; the default generic classes carry the mechanism vocabulary only."""
    presentation = presentation or Presentation()
    exempt = frozenset(c.strip().lower() for c in exempt_classes)

    # group leaves by confirmed (asset_class, role); unidentified leaves are FLAGGED, never bucketed
    by_class: dict = {}
    unidentified: list = []
    for leaf in leaves:
        conf = confirmed_structure.get(leaf.gl_account)
        if conf is None or conf.role not in (cost_role, contra_role):
            unidentified.append(leaf.gl_account)
            continue
        by_class.setdefault(conf.asset_class, {cost_role: [], contra_role: []})[conf.role].append(leaf)

    sections: list = []
    unclassified: set = set()
    for asset_class in sorted(by_class):
        roles = by_class[asset_class]
        cost_sched, u1 = _build_schedule(roles[cost_role], cost_config)
        contra_sched, u2 = _build_schedule(roles[contra_role], contra_config)
        unclassified |= u1 | u2
        sections.append(section_cls(
            asset_class=asset_class, cost_movement=cost_sched, contra_movement=contra_sched,
            cost_accounts=[l.gl_account for l in roles[cost_role]],
            contra_accounts=[l.gl_account for l in roles[contra_role]], exempt_classes=exempt))

    note = note_cls(
        note_ref=caption, sections=sections, presentation=presentation, anchor=anchor,
        unclassified_refs=sorted(unclassified), unidentified_accounts=sorted(unidentified),
        resolved=set(resolved or ()))
    return note, None
