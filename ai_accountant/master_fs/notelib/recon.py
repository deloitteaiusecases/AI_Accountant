"""The note reconciliation primitives — `TBAccount` (a TB leaf record) and `LineRecon` (the TB↔GL
keystone), relocated GL-free under master_fs (Slice 3).

The seed engine's note seam (`master_fs.notes.concept_anchor`) builds a `LineRecon` DIRECTLY with real
per-leaf attribution to prove a movement/breakdown note reconciles to its master concept (or BLOCKS). It
never used the GL routing front-end (`route_gl_to_tb`/`FaceTB`), so only these two records were carried
across; the `face_tb.classification` dependency lived on `FaceTB`, not `TBAccount`, so it is gone too.

Reconciliation target is the **raw** TB amount, never `Final` (recon-to-raw): reconciling to Final would
manufacture a false gap on every adjusted line. `raw + adjustment = Final` is a separate, visible bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Adjustment:
    column: str        # the source column name (named, auditable)
    value: float


@dataclass
class TBAccount:
    code: str                                  # normalised natural-account code ("" for a pure range row)
    level: str                                 # L0..L4
    account_type: str                          # "P" parent/scaffold | "C" child/leaf
    label: str
    range_lo: int | None = None
    range_hi: int | None = None
    raw_amount: float = 0.0                     # Amount (as per TB)
    adjustments: list[Adjustment] = field(default_factory=list)
    final_amount: float = 0.0                   # Final amount (from the file)
    mapping: str = ""                           # "Actual mapping" — verbatim (sub-designation preserved)
    section: str = ""                           # explicit L0-section tag, if the TB carries one
    source_row: int = -1
    raw_code: str = ""                          # pre-normalisation, for audit

    @property
    def is_leaf(self) -> bool:
        return self.account_type == "C"

    @property
    def code_int(self) -> int | None:
        return int(self.code) if self.code.isdigit() else None

    @property
    def has_amount(self) -> bool:
        return abs(self.final_amount) >= 0.005 or abs(self.raw_amount) >= 0.005

    @property
    def _adj_sum(self) -> float:
        return round(sum(a.value for a in self.adjustments), 2)

    @property
    def has_breakdown(self) -> bool:
        """The TB carries a raw + adjustment breakdown (not just a Final figure)."""
        return self.raw_amount != 0 or self._adj_sum != 0

    @property
    def recon_amount(self) -> float:
        """The figure GL reconciles to: the **raw** TB amount when a breakdown exists (recon-to-raw,
        R23), else the Final (a TB that gives only Final has no breakdown to reconcile against)."""
        return self.raw_amount if self.has_breakdown else self.final_amount

    @property
    def computed_final(self) -> float:
        return round(self.raw_amount + self._adj_sum, 2)

    @property
    def adjustment_ok(self) -> bool:
        """Final == raw + Σ adjustments — only meaningful when a breakdown exists; a Final-only TB
        has nothing to reconcile (no false mismatch)."""
        if not self.has_breakdown:
            return True
        return abs(self.computed_final - self.final_amount) < 0.005

    def in_range(self, code_int: int) -> bool:
        return (self.range_lo is not None and self.range_hi is not None
                and self.range_lo <= code_int <= self.range_hi)


@dataclass
class FaceTB:
    """A minimal trial-balance container — a flat list of `TBAccount` rows. The seed engine's
    `record_preparer_mappings` reads `amount_bearing_leaves()`; this is the thin holder it iterates."""
    accounts: list[TBAccount] = field(default_factory=list)

    def leaves(self) -> list[TBAccount]:
        return [a for a in self.accounts if a.is_leaf]

    def amount_bearing_leaves(self) -> list[TBAccount]:
        return [a for a in self.leaves() if a.has_amount]


@dataclass
class LineRecon:
    caption: str
    leaves_on_line: list[TBAccount]
    gl_by_code: dict[str, float] = field(default_factory=dict)   # covered TB-leaf code → GL Σ
    tol: float = 0.005                                            # rounding tolerance (TB units)

    @property
    def covered_leaves(self) -> list[TBAccount]:
        return [l for l in self.leaves_on_line if l.code in self.gl_by_code]

    @property
    def uncovered_leaves(self) -> list[TBAccount]:
        return [l for l in self.leaves_on_line if l.code not in self.gl_by_code]

    @property
    def tb_recon_covered(self) -> float:
        """Recon target: raw when a breakdown exists (recon-to-raw), else Final. Covered subtotal only."""
        return round(sum(l.recon_amount for l in self.covered_leaves), 2)

    @property
    def tb_final_covered(self) -> float:
        return round(sum(l.final_amount for l in self.covered_leaves), 2)

    @property
    def adjustment_bridge(self) -> float:
        """raw + adjustment = Final — the named bridge, shown; the recon does NOT use Final."""
        return round(self.tb_final_covered - self.tb_recon_covered, 2)

    @property
    def gl_sum(self) -> float:
        return round(sum(self.gl_by_code.values()), 2)

    @property
    def gap(self) -> float:
        """GL Σ − TB recon amount. Reconcile to the COVERED subtotal — not Final, not the whole line."""
        return round(self.gl_sum - self.tb_recon_covered, 2)

    @property
    def reconciles(self) -> bool:
        return abs(self.gap) < self.tol

    @property
    def fully_covered(self) -> bool:
        return not self.uncovered_leaves

    @property
    def coverage_pct(self) -> float:
        n = len(self.leaves_on_line)
        return round(100.0 * len(self.covered_leaves) / n, 1) if n else 0.0

    def status(self) -> str:
        if not self.reconciles:
            return "BLOCKED"                         # the gap is a real finding, not a tolerance
        return "BUILT" if self.fully_covered else "PARTIAL"
