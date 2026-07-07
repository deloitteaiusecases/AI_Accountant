"""ONE entry point for the master-FS flow: resolve seed → map/record → derive → render/export.

`seed_id` is passed EXPLICITLY in Slice A (no archetype detection yet — that is Slice B, and this is its
slot). Scripts and (later) the GUI both call `generate_master_fs`, so the flow lives in one place instead
of being inlined per script. Three mapping strategies:
  - "replay"   — `source` is a stored mapping result (the deterministic path; documents replay from it)
  - "preparer" — `source` is a FaceTB; the preparer's own captions are recorded (no AI)
  - "automap"  — `source` is (items, tb_rows); LIVE labels-only mapping, auto-applied as ai_assumed

The AI/arithmetic boundary is unchanged: automap is labels-only; rollups are seed-carried + human-authored.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_accountant.master_fs.mapping import (apply_mapping_decisions, propose_account_concepts,
                                             record_preparer_mappings)
from ai_accountant.master_fs.model import ClientMappingStore, ProvenanceStore
from ai_accountant.master_fs.seed import load_master_store
from ai_accountant.reporting.master_fs_export import (build_master_fs_export, export_master_fs_excel,
                                                      export_master_fs_pdf)


@dataclass
class MfsResult:
    model: object                  # the MfsExport (faces, provenance, findings, ...)
    stored: dict                   # the stored mapping result (replayable)
    master_id: str


def _stored_from_mapping(ms, client, master_id, tb_rows, extensions=None) -> dict:
    return {"client": client, "master_id": master_id, "tb": tb_rows, "extensions": extensions or [],
            "mappings": [{"account": r.account, "concept_id": r.concept_id, "client_label": r.client_label,
                          "provenance": r.provenance, "confidence": r.confidence,
                          "flagged_reason": r.flagged_reason} for r in ms.mapping(client).values()]}


def generate_master_fs(source, *, seed_id, client, period=(None, None), strategy="replay",
                       bank=None, at="", write_to=None, gl=None, disclaimer="") -> MfsResult:
    if not seed_id:                                        # a CONFIRMED seed_id is required — never
        raise ValueError("a confirmed seed_id is required")   # silently default (that would be a wrong route)
    store = load_master_store(seed_id=seed_id)

    if strategy == "replay":
        stored = source
    elif strategy == "preparer":
        ms, au = ClientMappingStore(), ProvenanceStore()
        record_preparer_mappings(source, store, client_id=client, mapping_store=ms, audit=au,
                                 approver="preparer", at=at)
        tb_rows = [{"account": a.code, "label": a.label, "current": a.final_amount, "prior": None}
                   for a in source.amount_bearing_leaves()]
        stored = _stored_from_mapping(ms, client, store.master_id, tb_rows)
    elif strategy == "automap":
        items, tb_rows = source
        proposals = propose_account_concepts(items, store)
        ms, au = ClientMappingStore(), ProvenanceStore()
        apply_mapping_decisions(proposals, store, client_id=client,
                                decisions={p.code: "assume" for p in proposals if p.is_confident},
                                mapping_store=ms, audit=au, approver="auto", at=at)
        stored = _stored_from_mapping(ms, client, store.master_id, tb_rows)
    else:
        raise ValueError(f"unknown strategy {strategy!r}")

    model = build_master_fs_export(store, stored, bank=bank, gl=gl, disclaimer=disclaimer,
                                   period_current=period[0], period_prior=period[1])
    if write_to:
        export_master_fs_excel(model, f"{write_to}.xlsx")
        export_master_fs_pdf(model, f"{write_to}.pdf")
    return MfsResult(model=model, stored=stored, master_id=store.master_id)
