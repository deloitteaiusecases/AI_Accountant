"""Per-note reference-code → movement-schedule line config.

Relocated GL-free under master_fs (Slice 2). Maps each SAP reference code to a line of a note's movement
schedule. An unmapped code is NOT dropped and NOT guessed — it rolls into an "Unclassified movement" line
that still ties into closing and is flagged for review (R3).

A note supplies its OWN ordered lines + code→line map (a commercial note like PP&E is not forced into the
Investments vocabulary). The seeded map is the confirmed-once store, not a closed list.
"""
from __future__ import annotations

from dataclasses import dataclass

# Movement-schedule lines, in disclosure order (between opening and closing).
ADDITIONS = "Additions / purchases"
DISPOSALS = "Disposals"
MATURITIES = "Maturities"
REMEASUREMENT = "Remeasurement (fair value / EIR)"
FX = "Foreign exchange revaluation"
ECL_CHARGE = "ECL charge / (release)"
UNCLASSIFIED = "Unclassified movement"

MOVEMENT_LINES = [ADDITIONS, DISPOSALS, MATURITIES, REMEASUREMENT, FX, ECL_CHARGE, UNCLASSIFIED]


@dataclass(frozen=True)
class MovementConfig:
    name: str
    ordered_lines: tuple                         # disclosure order, between opening and closing
    ref_to_line: tuple                           # ((REF_CODE_UPPER, line), …) — frozen for the seed

    def classify(self, code: str) -> tuple:
        """(line, is_mapped). Unknown/blank code → the Unclassified line, flagged but still in closing."""
        c = (code or "").strip().upper()
        for ref, line in self.ref_to_line:
            if ref == c:
                return line, True
        return UNCLASSIFIED, False


# PP&E movement lines — its OWN vocabulary, not Investments'. OPEN-BF is the opening (not a movement):
# opening rows land in the leaf's opening, never in movement_by_ref.
PPE_ADDITIONS = "Additions"
PPE_DISPOSALS_COST = "Disposals (cost)"
PPE_TRANSFERS = "Transfers"
PPE_DEP_CHARGE = "Depreciation charge"
PPE_DISPOSALS_DEP = "Disposals (accumulated depreciation)"

PPE_COST_CONFIG = MovementConfig(
    name="PP&E — cost",
    ordered_lines=(PPE_ADDITIONS, PPE_DISPOSALS_COST, PPE_TRANSFERS, UNCLASSIFIED),
    ref_to_line=(("ADD-PURCH", PPE_ADDITIONS), ("DISP-COST", PPE_DISPOSALS_COST),
                 ("TRANSFER", PPE_TRANSFERS)))
PPE_DEP_CONFIG = MovementConfig(
    name="PP&E — accumulated depreciation",
    ordered_lines=(PPE_DEP_CHARGE, PPE_DISPOSALS_DEP, UNCLASSIFIED),
    ref_to_line=(("DEP-CHG", PPE_DEP_CHARGE), ("DISP-DEP", PPE_DISPOSALS_DEP)))

# Intangible-assets movement lines — the SAME two-layer mechanism, intangibles' OWN vocabulary: the
# contra is AMORTIZATION (not depreciation). The note caption + this config carry the intangibles voice;
# the generic builder (movement.py) stays vocabulary-free.
INTANGIBLE_ADDITIONS = "Additions"
INTANGIBLE_DISPOSALS_COST = "Disposals (cost)"
INTANGIBLE_TRANSFERS = "Transfers"
INTANGIBLE_AMORT_CHARGE = "Amortization charge"
INTANGIBLE_DISPOSALS_AMORT = "Disposals (accumulated amortization)"

INTANGIBLE_COST_CONFIG = MovementConfig(
    name="Intangible assets — cost",
    ordered_lines=(INTANGIBLE_ADDITIONS, INTANGIBLE_DISPOSALS_COST, INTANGIBLE_TRANSFERS, UNCLASSIFIED),
    ref_to_line=(("ADD-PURCH", INTANGIBLE_ADDITIONS), ("DISP-COST", INTANGIBLE_DISPOSALS_COST),
                 ("TRANSFER", INTANGIBLE_TRANSFERS)))
INTANGIBLE_AMORT_CONFIG = MovementConfig(
    name="Intangible assets — accumulated amortization",
    ordered_lines=(INTANGIBLE_AMORT_CHARGE, INTANGIBLE_DISPOSALS_AMORT, UNCLASSIFIED),
    ref_to_line=(("AMORT-CHG", INTANGIBLE_AMORT_CHARGE), ("DISP-AMORT", INTANGIBLE_DISPOSALS_AMORT)))

# Name → MovementConfig registry: a seed note declares its configs by NAME (a string the seed can carry);
# the orchestrator resolves the name to the config here. Keeps the config OBJECTS out of the JSON seed
# while the engine code names no specific note.
MOVEMENT_CONFIGS = {
    "ppe_cost": PPE_COST_CONFIG, "ppe_dep": PPE_DEP_CONFIG,
    "intangible_cost": INTANGIBLE_COST_CONFIG, "intangible_amort": INTANGIBLE_AMORT_CONFIG,
}


def movement_config(name: str) -> MovementConfig:
    """Resolve a seed-declared config name to its MovementConfig, or fail loud (never silently default)."""
    try:
        return MOVEMENT_CONFIGS[name]
    except KeyError:
        raise KeyError(f"unknown movement config {name!r} — declare it in MOVEMENT_CONFIGS "
                       f"(known: {sorted(MOVEMENT_CONFIGS)})")
