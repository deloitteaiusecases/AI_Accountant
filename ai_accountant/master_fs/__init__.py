"""Master FS structure (phase 1) — generate BS / P&L / OCI from a TB against a shared, human-approved
master. The master is fixed (seeded from the approved xlsx via GATE 0); the AI maps INTO it and
proposes ADDITIONS, never invents; the master holds STRUCTURE ONLY, never an amount. Reuses the
existing engine (TB ingestion, signal mapping, propose-confirm-store, the pinned proposers).
"""
from __future__ import annotations

from ai_accountant.master_fs.detect import ArchetypeProposal, ArchetypeRanking, archetype_verdict
from ai_accountant.master_fs.mapping import (ExtensionDecision, MaturitySplitProposal,
                                             apply_mapping_decisions, confirm_archetype,
                                             confirm_master_extension, concept_for_label,
                                             propose_account_concepts, propose_archetype,
                                             propose_master_extension, propose_master_extensions,
                                             propose_maturity_split, propose_note_agenda, agenda_payload,
                                             propose_static_breakdown, record_preparer_mappings)
from ai_accountant.master_fs.model import (AI_ASSUMED, AI_CONFIRMED, AuditRecord, ClientMappingStore,
                                           MappingRecord, MasterConcept, MasterStructureStore, PREPARER,
                                           ProvenanceStore)
from ai_accountant.master_fs.derive import (apply_carries, balance_difference, coverage_leaves,
                                            derive_statement, orphan_leaves, topo_order)
from ai_accountant.master_fs.render import (ComparativeLine, RenderedLine, carried_leaf_amounts,
                                            leaf_amounts, render_comparative, render_master_fs,
                                            render_statement)
from ai_accountant.master_fs.notes import (apply_split, assert_sign_convention, attach_movement_note,
                                           attach_ppe_note, attach_split_note, attach_static_breakdown,
                                           concept_anchor, confirm_split, detect_split_case, group_by_label,
                                           note_findings, note_status, record_maturity_split,
                                           record_sign_convention)
from ai_accountant.master_fs.orchestrator import MfsResult, generate_master_fs
from ai_accountant.master_fs.gate0 import validate_csv, validate_seed
from ai_accountant.master_fs.seed import (load_all_masters, load_detect_thresholds, load_master_store,
                                          load_registry)
from ai_accountant.master_fs.validate import validate_engine_meta, validate_rollups

__all__ = ["load_master_store", "load_registry", "load_all_masters", "load_detect_thresholds",
           "generate_master_fs", "MfsResult",
           "propose_archetype", "confirm_archetype", "archetype_verdict", "ArchetypeProposal",
           "ArchetypeRanking",
           "attach_ppe_note", "attach_movement_note", "concept_anchor", "assert_sign_convention",
           "record_sign_convention",
           "note_findings", "note_status", "detect_split_case", "apply_split", "attach_split_note",
           "record_maturity_split", "confirm_split", "propose_maturity_split", "MaturitySplitProposal",
           "attach_static_breakdown", "propose_static_breakdown", "group_by_label",
           "validate_seed", "validate_csv", "validate_rollups",
           "validate_engine_meta", "MasterConcept",
           "MasterStructureStore", "ClientMappingStore", "ProvenanceStore", "MappingRecord",
           "AuditRecord", "PREPARER", "AI_CONFIRMED", "AI_ASSUMED",
           "record_preparer_mappings", "propose_account_concepts", "apply_mapping_decisions",
           "propose_master_extension", "propose_master_extensions", "ExtensionDecision",
           "confirm_master_extension", "concept_for_label",
           "render_master_fs", "render_statement", "render_comparative", "RenderedLine",
           "ComparativeLine", "leaf_amounts", "carried_leaf_amounts",
           "derive_statement", "topo_order", "orphan_leaves", "coverage_leaves",
           "balance_difference", "apply_carries"]
