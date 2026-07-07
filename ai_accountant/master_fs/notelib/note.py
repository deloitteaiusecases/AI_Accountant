"""The Note value object — an authoritative total + a reconciling breakdown, with honest status.

Relocated GL-free under master_fs (Slice 2 of the GL-pipeline removal): the seed engine's movement/PP&E
notes reuse `Presentation` from here. The only former GL coupling was a TYPE_CHECKING hint on `LineRecon`;
with `from __future__ import annotations` every annotation is a string at runtime, so the hint needs no
import and the anchor stays duck-typed (the real reconciliation object is injected by the caller).

Two states are kept deliberately separate: the breakdown can be fully *computed* while the note is still
not *final*. `tie_ok` proves Σ lines == account total to the cent; `status()` is BUILT only when the tie
holds AND the presentation unit is confirmed (R11) AND nothing upstream is provisional.

Figures are stored in raw absolute SAR. Presentation scaling (e.g. SAR'000) is applied only once the unit
is explicitly confirmed — never silently inherited.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteLine:
    label: str
    amount_sar: float                  # raw absolute SAR (pre-scale)
    n_postings: int = 0
    is_control_flag: bool = False      # a flagged control artifact, not a real sub-category
    is_brought_forward: bool = False   # the opening/take-on line — structural, not a sub-category
    needs_source: bool = False         # unlabelled rows routed to source recovery, never the AI
    pending_reclassification: bool = False  # confirmed not-a-prepayment; held for finance to move


# The unit label is DERIVED from the scale — one source of truth. A free-text label decoupled from
# the divisor is how a note ends up showing absolute SAR under a "SAR'000" header (a 1000× lie).
_UNIT_LABELS = {1: "SAR", 1000: "SAR'000", 1_000_000: "SAR millions"}


@dataclass
class Presentation:
    scale: int = 1                     # 1 = SAR, 1000 = SAR'000, 1_000_000 = SAR millions
    confirmed: bool = False            # R11 gate — figures are not presented until this is True

    @property
    def unit_label(self) -> str:
        """Always consistent with `scale` — never a hand-set string that could disagree."""
        return _UNIT_LABELS.get(self.scale, f"SAR ÷{self.scale}")


@dataclass
class Note:
    note_ref: str
    account_total_sar: float           # the authoritative, deterministic total (from the GL/TB)
    lines: list[NoteLine] = field(default_factory=list)
    presentation: Presentation = field(default_factory=Presentation)
    upstream_status: str = "BUILT"     # RollForwardTB.status() for the note's account(s)
    upstream_reasons: list[str] = field(default_factory=list)
    other_pending: int = 0             # count of postings sitting in "Other" awaiting refinement
    provisional_outlook: str = ""      # the DIRECTION the open items will move the figure (R20)
    resolved: set[str] = field(default_factory=set)   # concerns the human has answered (R8 recompile)
    anchor: "LineRecon | None" = None  # the anchoring TB line's reconciliation (slice-5 inversion)

    @property
    def control_flags(self) -> list[NoteLine]:
        return [l for l in self.lines if l.is_control_flag]

    @property
    def internal_tie_ok(self) -> bool:
        """STRUCTURAL: Σ sub-category lines == the breakdown's own total. No longer the authority — an
        internal tie can be perfectly consistent and still disagree with the TB line (the lesson the
        Prepayments double-count paid for). Demoted from `tie_ok` to a structural precondition."""
        return abs(sum(l.amount_sar for l in self.lines) - self.account_total_sar) < 0.005

    @property
    def reconciles_to_tb(self) -> bool:
        """The inverted contract: the breakdown reconciles UP to its anchoring TB line — via the SAME
        `LineRecon` the Bucket C keystone uses (recon-to-raw; one path, not two). False with no anchor."""
        return self.anchor is not None and self.anchor.reconciles

    @property
    def tie_ok(self) -> bool:
        """FLIPPED (slice 5): reconciles to the TB line AND is internally consistent. With no anchor
        this is False — magnitude-unverified, NEVER silently True."""
        return self.reconciles_to_tb and self.internal_tie_ok

    def provisional_reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.internal_tie_ok:
            reasons.append("sub-category breakdown does not add up to its own total (structural)")
        if self.anchor is None:
            reasons.append("MAGNITUDE UNVERIFIED (R16): no anchoring TB line — the breakdown is not "
                           "reconciled to a position (internal ties prove wiring, not magnitude)")
        elif not self.reconciles_to_tb:
            reasons.append(f"internally consistent but does NOT reconcile to the TB line "
                           f"(Δ = {self.anchor.gap:,.2f} TB-units) — reconciliation BLOCKS; internal "
                           f"consistency cannot upgrade it")
        elif not self.anchor.fully_covered:
            reasons.append(f"GL covers {self.anchor.coverage_pct}% of the TB line's leaves — reconciled "
                           f"to the covered subtotal; uncovered: "
                           f"{[l.code for l in self.anchor.uncovered_leaves]}")
        if not self.presentation.confirmed:
            reasons.append("presentation unit/scale not confirmed (R11) — figures not yet presented")
        if self.control_flags and "control_artifact" not in self.resolved:
            amt = sum(l.amount_sar for l in self.control_flags)
            reasons.append(f"{len(self.control_flags)} control-artifact line(s) flagged "
                           f"({amt:,.2f} SAR) — confirm reclassification, not bucketed")
        if self.other_pending and "other" not in self.resolved:
            reasons.append(f"{self.other_pending} posting(s) in 'Other' awaiting AI/human refinement")
        src = [l for l in self.lines if l.needs_source]
        if src and "source" not in self.resolved:
            amt = sum(l.amount_sar for l in src)
            reasons.append(f"{len(src)} unlabelled line(s) ({amt:,.2f} SAR) need source/description "
                           f"recovery — routed to a human, never the AI")
        reclass = [l for l in self.lines if l.pending_reclassification]
        if reclass and "reclass" not in self.resolved:
            amt = sum(l.amount_sar for l in reclass)
            reasons.append(f"{len(reclass)} flagged not-a-prepayment line(s) ({amt:,.2f} SAR) await "
                           f"finance reclassification — held in this note's total, not relocated")
        reasons.extend(self.upstream_reasons)
        return reasons

    def status(self) -> str:
        """BLOCKED if no total OR the breakdown fails to reconcile to its TB line (the internal-tie-
        that-lies guard — a reconciliation BLOCK overrides everything); BUILT if nothing provisional;
        else PARTIAL."""
        if self.account_total_sar is None:
            return "BLOCKED"
        if self.anchor is not None and self.anchor.status() == "BLOCKED":
            return "BLOCKED"                 # internally consistent but ≠ TB line — never upgraded
        return "BUILT" if not self.provisional_reasons() else "PARTIAL"

    def status_line(self) -> str:
        """Headline: status + the figure AT THE PRESENTED SCALE with the matching label (R11).

        The figure here and the figure in the table must be in the same unit — so the headline uses
        the presentation, not a hardcoded absolute-SAR figure. Withheld until the unit is confirmed.
        """
        if not self.presentation.confirmed:
            return f"{self.status()} — provisional figure withheld until unit confirmed"
        val = round(self.account_total_sar / self.presentation.scale, 2)
        return f"{self.status()} — provisional {val:,.2f} {self.presentation.unit_label}"

    def presented(self, line: NoteLine) -> float | None:
        """Scaled figure — only meaningful once the unit is confirmed (R11); else None."""
        if not self.presentation.confirmed:
            return None
        return round(line.amount_sar / self.presentation.scale, 2)
