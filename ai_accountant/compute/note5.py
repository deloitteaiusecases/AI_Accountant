"""Note 5 (Investments, Net) orchestration.

Ties the pieces together: detect tables -> run the L4->L3->L2->L1 cascade -> reconcile
against ground truth. Returns one structured result the UI (or a CLI) can render.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_accountant.compute.cascade import CascadeResult, compute_cascade
from ai_accountant.ingestion.collect import (
    collect_from_filelike,
    collect_from_files,
    collect_from_path,
)
from ai_accountant.ingestion.table_detect import DetectedTable
from ai_accountant.policy import apply_classification
from ai_accountant.routing import build_routing_map
from ai_accountant.routing.models import RoutingMap
from ai_accountant.validation.audit import AuditTrail, build_audit_trail
from ai_accountant.validation.controls import ConfidenceReport, run_controls
from ai_accountant.validation.reconcile import (
    ReconLine,
    ReconSection,
    all_match,
    build_reconciliation,
    reconcile_l1,
)


@dataclass
class Note5Result:
    tables: list[DetectedTable]
    cascade: CascadeResult
    reconciliation: list[ReconLine]
    reconciled: bool
    routing: RoutingMap
    classifications: list[dict] = field(default_factory=list)
    reconciliation_report: list[ReconSection] = field(default_factory=list)
    audit: AuditTrail = field(default_factory=AuditTrail)
    confidence: ConfidenceReport = field(default_factory=ConfidenceReport)
    confidence_narrative: str = ""  # optional LLM summary, set by the UI layer (never in _build)

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.tables:
            counts[t.level or "?"] = counts.get(t.level or "?", 0) + 1
        return counts


def _build(tables: list[DetectedTable], policy_rules: list[dict] | None = None) -> Note5Result:
    # Fill any missing classifications (policy first, IFRS 9 fallback) before computing.
    decisions = apply_classification(tables, policy_rules)
    routing = build_routing_map(tables)
    cascade = compute_cascade(tables)
    recon = reconcile_l1(cascade.l1)
    report = build_reconciliation(tables, cascade.l1)
    audit = build_audit_trail(tables, cascade)
    confidence = run_controls(tables, cascade)
    return Note5Result(tables, cascade, recon, all_match(recon), routing, decisions,
                       reconciliation_report=report, audit=audit, confidence=confidence)


def run_note5_from_path(path: str) -> Note5Result:
    return _build(collect_from_path(path))


def run_note5_from_filelike(file: Any) -> Note5Result:
    return _build(collect_from_filelike(file))


def run_note5_from_files(
    files: list[Any], api_key: str | None = None, policy_rules: list[dict] | None = None,
) -> Note5Result:
    """Build Note 5 from many uploaded files (CSV/Excel, multi-sheet, multi-table).

    Fast path: a single LARGE holdings CSV is streamed in memory-bounded chunks.
    Otherwise tables are collected in-memory. If `api_key` is given, AI column-mapping
    canonicalizes foreign schemas the alias layer couldn't recognize before computing.
    `policy_rules` (from an uploaded policy) drive classification of securities missing one.
    """
    if len(files) == 1:
        streamed = _try_stream_single_file(files[0])
        if streamed is not None:
            return streamed

    tables = collect_from_files(files)
    if api_key:
        from ai_accountant.routing import ai_normalize_tables
        ai_normalize_tables(tables, api_key)
    return _build(tables, policy_rules)


def _try_stream_single_file(file: Any) -> Note5Result | None:
    """Return a streamed Note5Result if `file` is a large single holdings CSV, else None."""
    from ai_accountant.compute.streaming import looks_like_large_holdings, stream_cascade_from_csv
    from ai_accountant.ingestion.loaders import is_large
    from ai_accountant.routing.models import RoutingEntry

    name = getattr(file, "name", "")
    if not name.lower().endswith(".csv") or not is_large(file) or not looks_like_large_holdings(file):
        return None

    cascade = stream_cascade_from_csv(file)
    placeholder = DetectedTable(
        level="L3", title="(streamed) sub-ledger",
        headers=list(cascade.l3_holdings.columns), records=[], source_file=name,
    )
    routing = RoutingMap(entries=[RoutingEntry(
        source_file=name, level="L3", role="sub-ledger holdings (streamed)",
        note="Note 5: Investments", used_in_cascade=True, confidence="rule",
    )], reasoning="Large single-table file streamed in chunks.")
    recon = reconcile_l1(cascade.l1)
    return Note5Result([placeholder], cascade, recon, all_match(recon), routing)
