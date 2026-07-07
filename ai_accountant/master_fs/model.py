"""Master FS structure — the three logically-separate, DB-ready stores (built on files/in-memory).

(1) the GLOBAL master structure (concepts; seed + confirmed extensions), (2) PER-CLIENT confirmed
mappings (keyed by client so one bank's mappings never leak to another), (3) PROVENANCE/audit. Each
record carries the fields a future DB would need (stable IDs, provenance, master-vs-per-client) so
deployment is a swap, not a back-fill — but there is NO DB engine here. The master holds STRUCTURE
ONLY: `MasterConcept` has deliberately no amount/value field — amounts live with each client's TB.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# provenance values, used everywhere a classification is recorded
PREPARER = "preparer"                 # the accountant's own mapping (with-mappings path)
AI_CONFIRMED = "ai_confirmed"         # AI-proposed, a human reviewed and confirmed it
AI_ASSUMED = "ai_assumed"            # AI-proposed, accepted unverified — flagged, never BUILT
HUMAN_APPROVED_TEMPLATE = "human_approved_template"   # the seed itself


@dataclass(frozen=True)
class MasterConcept:
    concept_id: str                   # stable id (seed-assigned, namespaced per archetype)
    statement: str                    # which statement this concept belongs to (a seed-declared key)
    l0_section: str
    l1_group: str | None
    canonical_concept: str
    label_aliases: dict               # bank -> the bank's own label for this concept
    presence: str                     # seed-declared: which source entities carry this concept
    order: int                        # liquidity-order position within the statement
    provenance: str = HUMAN_APPROVED_TEMPLATE
    kind: str = "leaf"                 # leaf | net | subtotal | total — computed kinds are DERIVED
    #                                   deterministically from `components`, NEVER mapped/AI-touched.
    components: tuple = ()             # for computed kinds: ((sign, concept_id), ...), sign in {"+","-"}
    caveat: str = ""                   # a seed-declared honesty marker (e.g. an estimated balancing residual):
    #                                   when this leaf is populated the build raises a face-visible finding +
    #                                   judgment marker + not_final — the line is shown, never silently clean.
    caveat_kind: str = ""              # the SHORT on-face tag label for `caveat` (seed DATA, e.g. "estimated
    #                                   residual") — so the face tag reads the marker's own kind, not a generic one.
    # NOTE: there is NO amount/value field, by design — the master is structure only.

    def label_for(self, bank: str) -> str:
        return self.label_aliases.get(bank) or self.canonical_concept

    @property
    def is_computed(self) -> bool:    # a derived line (engine arithmetic), not a mappable leaf
        return self.kind in ("net", "subtotal", "total")


@dataclass
class MasterStructureStore:           # store (1) — per-master structure (seed-driven)
    concepts: dict = field(default_factory=dict)   # concept_id -> MasterConcept
    meta: dict = field(default_factory=dict)       # the seed's `engine` block — ALL archetype facts
    master_id: str = ""                            # which master/archetype this store is (registry id)

    def get(self, concept_id: str) -> "MasterConcept | None":
        return self.concepts.get(concept_id)

    def by_canonical(self, canonical: str) -> "MasterConcept | None":
        for c in self.concepts.values():
            if c.canonical_concept == canonical:
                return c
        return None

    def statement(self, statement: str) -> list:
        return sorted((c for c in self.concepts.values() if c.statement == statement),
                      key=lambda c: c.order)

    # ---- seed-declared structural roles (read from `meta`, never literals) ----
    def _stmt(self, key):
        return next((s for s in self.meta.get("statements", []) if s["key"] == key), None)

    def statement_keys(self) -> list:
        return [s["key"] for s in self.meta.get("statements", [])]

    def statement_title(self, key: str) -> str:
        s = self._stmt(key)
        return s["title"] if s else key

    def sections(self, statement: str) -> list:
        """The statement's DECLARED sections (authoritative placement order)."""
        s = self._stmt(statement)
        return list(s.get("sections", [])) if s else []

    def all_sections_ordered(self) -> list:
        out = []
        for s in self.meta.get("statements", []):
            out += [sec for sec in s.get("sections", []) if sec not in out]
        return out

    def sections_present(self, statement: str) -> list:
        """Sections actually appearing among this statement's concepts (for load-time validation)."""
        seen, out = set(), []
        for c in self.statement(statement):
            if c.l0_section not in seen:
                seen.add(c.l0_section)
                out.append(c.l0_section)
        return out

    def coverage_totals(self, statement: str) -> tuple:
        s = self._stmt(statement)
        return tuple(s.get("coverage_totals", [])) if s else ()

    def balance_check(self) -> "dict | None":
        return self.meta.get("balance_check")

    def memo_leaves(self) -> frozenset:
        return frozenset(self.meta.get("memo_leaves", []))

    def carry_leaves(self) -> list:
        """[{id, from}] — a leaf the engine populates deterministically from its `from` concept's
        derived value (e.g. OCI's net-income line carried from the P&L total). Seed-declared, no AI."""
        return list(self.meta.get("carry_leaves", []))

    def carry_leaf_ids(self) -> frozenset:
        return frozenset(c.get("id") for c in self.meta.get("carry_leaves", []))

    def notes(self) -> list:
        """[{concept, mechanism, anchor}] — seed-declared note breakdowns attached to face concepts."""
        return list(self.meta.get("notes", []))

    def note_for(self, concept_id: str) -> "dict | None":
        return next((n for n in self.meta.get("notes", []) if n.get("concept") == concept_id), None)

    def default_placement(self) -> dict:
        return self.meta.get("default_placement", {})

    def prompts(self) -> dict:
        return self.meta.get("prompts", {})

    @property
    def presentation(self) -> "str | None":
        return self.meta.get("presentation")

    @property
    def current_non_current_split(self) -> bool:
        return bool(self.meta.get("current_non_current_split", False))

    def maturity_pairs(self) -> tuple:
        """Seed-DERIVED current/non-current concept pairs, gated on `current_non_current_split` (a liquidity-
        presented seed like the bank has none → ([], [])). A CLEAN pair is exactly one '… — non-current' leaf
        and one '… — current' leaf sharing the same base name. Anything else — an orphan half, a same-side
        collision, or >2 sharing a base — is AMBIGUOUS and SURFACED (never silently paired or skipped); the
        AI-fallback pairing + a human confirm resolve those. Returns (clean_pairs[(nc,c)], ambiguous[dict])."""
        import re
        if not self.current_non_current_split:
            return [], []
        rx = re.compile(r"\s*[-—–]\s*(non-current|current)\s*$", re.IGNORECASE)
        halves: dict = {}
        for c in self.concepts.values():
            if c.kind != "leaf":
                continue
            m = rx.search(c.canonical_concept)
            if not m:
                continue                                     # not a declared maturity half (a normal single leaf)
            side = "nc" if "non" in m.group(1).lower() else "c"
            base = rx.sub("", c.canonical_concept).strip().lower()
            halves.setdefault(base, {"nc": [], "c": []})[side].append(c.concept_id)
        clean, ambiguous = [], []
        for base, s in halves.items():
            if len(s["nc"]) == 1 and len(s["c"]) == 1:
                clean.append((s["nc"][0], s["c"][0]))
            else:
                ambiguous.append({"base": base, "nc": list(s["nc"]), "c": list(s["c"])})
        return clean, ambiguous

    def next_order(self, statement: str, l0_section: str) -> int:
        """A coherent placement slot at the end of a section's LEAF block (the human confirms it).
        Computed concepts (section totals at sentinel order 999/1000) are ignored, so a new leaf lands
        among the leaves — BEFORE its section total, never after it."""
        same = [c.order for c in self.concepts.values()
                if c.statement == statement and c.l0_section == l0_section and not c.is_computed]
        return (max(same) + 5) if same else 10

    def add(self, concept: MasterConcept) -> None:
        self.concepts[concept.concept_id] = concept           # confirmed extension


@dataclass
class MappingRecord:                  # one account -> concept, for one client (of one master)
    account: str
    concept_id: str | None            # None = UNMAPPED (unsure / flagged) — never force-mapped
    client_label: str                 # the client's OWN label, preserved for display
    provenance: str                   # PREPARER | AI_CONFIRMED | AI_ASSUMED
    confidence: str = ""
    approver: str = ""
    approved_at: str = ""
    flagged_reason: str = ""          # why it is unmapped (e.g. "unsure — no confident concept")
    master_id: str = ""               # which master the concept_id belongs to (scopes the mapping)

    @property
    def is_mapped(self) -> bool:
        return self.concept_id is not None


@dataclass
class ClientMappingStore:             # store (2) — per (master, client); cannot leak across archetypes
    by_client: dict = field(default_factory=dict)   # (master_id, client_id) -> {account -> MappingRecord}

    def put(self, client_id: str, rec: MappingRecord) -> None:
        self.by_client.setdefault((rec.master_id, client_id), {})[rec.account] = rec

    def mapping(self, client_id: str, master_id: "str | None" = None) -> dict:
        if master_id is not None:
            return self.by_client.get((master_id, client_id), {})
        hits = [v for (mid, cid), v in self.by_client.items() if cid == client_id]
        if len(hits) > 1:                 # leak-safe: one client_id must not span masters silently
            masters = [mid for (mid, cid) in self.by_client if cid == client_id]
            raise ValueError(f"client_id {client_id!r} spans masters {masters}; pass master_id")
        return hits[0] if hits else {}

    def concept_of(self, client_id: str, account: str, master_id: "str | None" = None) -> "str | None":
        rec = self.mapping(client_id, master_id).get(account)
        return rec.concept_id if rec else None


@dataclass
class AuditRecord:                    # store (3) — provenance / audit
    action: str                       # "map_account" | "extend_master"
    target: str                       # the account or the new concept_id
    client_id: str
    provenance: str
    confidence: str
    approver: str
    at: str
    detail: str = ""


@dataclass
class ProvenanceStore:
    records: list = field(default_factory=list)

    def log(self, rec: AuditRecord) -> None:
        self.records.append(rec)

    def for_client(self, client_id: str) -> list:
        return [r for r in self.records if r.client_id == client_id]
