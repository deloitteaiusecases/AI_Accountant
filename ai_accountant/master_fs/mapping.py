"""Map a client's TB accounts INTO the master concepts (signal-based) and propose ADDITIONS.

Reuses the existing propose-confirm-store proposers (labels-only, pinned model) — the master
`canonical_concept` list is the candidate vocabulary. The AI proposes; a human confirms; the confirmed
mapping is stored per-client with provenance. NEVER force-mapped: an unsure / unconfident proposal
stays UNMAPPED and flagged. A line no concept covers is PROPOSED as a new master concept WITH a
placement (section + order) the human confirms — structure only, never an amount.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ai_accountant.master_fs.notelib.propose import FaceMappingProposal, propose_seed_mapping
from ai_accountant.master_fs.model import (AI_ASSUMED, AI_CONFIRMED, AuditRecord, MappingRecord,
                                           MasterConcept, PREPARER)

# GENERIC mapping prompt template — archetype-specific text (domain, master description, vocabulary) is
# injected from the ACTIVE seed's `engine.prompts`, so the template carries NO archetype/vocabulary literal.
# LABELS ONLY — never amounts. One concept per line, verbatim from the candidate list, or 'unsure'.
_MASTER_TEMPLATE = (
    "You are the classification layer of an auditable financial-statement generator for <<DOMAIN>>. "
    "Your sole task: map each trial-balance face-line LABEL to exactly ONE concept from a fixed MASTER "
    "list of financial-statement concepts (<<MASTER_DESC>>). You are given each line's account code and "
    "its LABEL only — NEVER any amount, and you must NOT ask for one. Rules:\n"
    "1. READ THE LABEL, not the account code — codes can be renumbered, foreign, or meaningless. Use "
    "the code only as a weak tie-breaker if a label is ambiguous.\n"
    "2. Choose EXACTLY one concept from the candidate list, copied VERBATIM, or return 'unsure'.\n"
    "3. <<HINTS>>\n"
    "4. A CONTRA (an allowance / ECL / impairment / accumulated depreciation) belongs with the asset it "
    "offsets — map it to that asset's concept, never to its own unrelated line.\n"
    "5. Distinguish the statements: balance-sheet captions vs income-statement captions vs other-"
    "comprehensive-income captions ('FVOCI fair-value change', 're-measurement of defined benefit', "
    "'cash flow hedge', 'exchange differences on translation').\n"
    "6. If NO candidate genuinely fits, or the label is too vague to be sure, return concept='unsure' "
    "and confidence='low' — NEVER force a line into the nearest-looking concept. Being conservatively "
    "unsure is correct; a confident wrong mapping is the worst outcome.\n"
    "7. ALWAYS cite the exact words in the label that drove your choice (evidence), and give a "
    "confidence of high | medium | low.\n"
    "8. Output EXACTLY one JSON object, no prose: {\"proposals\":[{\"account\":..,\"concept\":..,"
    "\"confidence\":\"high|medium|low\",\"evidence\":..}]}"
)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _assemble_master_system(master_store) -> str:
    """Assemble the mapping system prompt from the active seed's injected pieces (domain / description /
    vocabulary hints). For the original seed this reproduces the prior prompt byte-for-byte (Leg 2)."""
    p = master_store.prompts()
    return (_MASTER_TEMPLATE.replace("<<DOMAIN>>", p.get("domain", ""))
            .replace("<<MASTER_DESC>>", p.get("master_desc", ""))
            .replace("<<HINTS>>", p.get("mapping_hints", "")))


def propose_master_mappings(items, candidates, *, system, entity_noun="entity", client=None) -> list:
    """items: (account, label). candidates: the master canonical concepts. Maps each label to one
    concept (verbatim) or 'unsure', with confidence + evidence — via the pinned `gpt-5.1-2025-11-13`
    client, LABELS ONLY (no amounts ever sent). `system` is the assembled (seed-driven) system prompt.
    Returns FaceMappingProposal objects (code=account, line=concept) for the same confirm/store path."""
    from ai_accountant.llm.client import LLMClient
    client = client or LLMClient()
    cand = "\n".join(f"- {c}" for c in candidates)
    rows = "\n".join(f"{acct}\t{label}" for acct, label in items)
    prompt = (f"MASTER concepts (choose verbatim, or 'unsure'):\n{cand}\n\n"
              f"{entity_noun.capitalize()} trial-balance lines (account <tab> label) — LABELS ONLY, "
              f"no amounts:\n{rows}")
    raw = client.complete_json(prompt, system=system)
    by = {}
    for p in raw.get("proposals", []):
        if isinstance(p, dict):
            by[str(p.get("account", p.get("code", ""))).strip()] = p
    out = []
    for acct, label in items:
        p = by.get(acct, {})
        out.append(FaceMappingProposal(
            code=acct, label=label, line=str(p.get("concept", p.get("line", "unsure"))),
            confidence=str(p.get("confidence", "low")), evidence=str(p.get("evidence", ""))))
    return out


def concept_for_label(master_store, label) -> "MasterConcept | None":
    """Exact (canonical or alias) match — used for the PREPARER path (the client's own caption)."""
    n = _norm(label)
    for c in master_store.concepts.values():
        if _norm(c.canonical_concept) == n or any(_norm(v) == n for v in c.label_aliases.values()):
            return c
    return None


# ---- PREPARER path (with-mappings): record the client's own mappings, provenance=preparer ----------
def record_preparer_mappings(facetb, master_store, *, client_id, mapping_store, audit, approver, at) -> list:
    """Each amount-bearing leaf's own `mapping` → its master concept (exact match), provenance=preparer.
    A caption matching no concept stays unmapped+flagged (a candidate for a confirmed extension)."""
    unmatched = []
    for leaf in facetb.amount_bearing_leaves():
        concept = concept_for_label(master_store, leaf.mapping) if leaf.mapping.strip() else None
        bad = concept is not None and (concept.is_computed or concept.concept_id in master_store.carry_leaf_ids())
        reason = (f"amount mapped to computed/carry concept {concept.concept_id} — left open" if bad
                  else ("" if concept else "preparer caption matches no master concept"))
        rec = MappingRecord(account=leaf.code, concept_id=(None if bad or concept is None else concept.concept_id),
                            client_label=leaf.mapping or leaf.label, provenance=PREPARER,
                            approver=approver, approved_at=at, master_id=master_store.master_id,
                            flagged_reason=reason)                # BLOCK a bad target — never place, never drop
        mapping_store.put(client_id, rec)
        if concept is None or bad:
            unmatched.append(leaf.code)
        else:
            audit.log(AuditRecord("map_account", leaf.code, client_id, PREPARER, "", approver, at,
                                  detail=f"-> {concept.concept_id}"))
    return unmatched


# ---- AI path (no-mappings): propose → confirm/assume → store; unsure stays unmapped -----------------
def propose_account_concepts(items, master_store, *, client=None) -> list:
    """items: (account, label). Proposes one master concept per account, by SIGNAL, with 'unsure'
    available — labels-only, pinned model. Both the candidate vocabulary AND the system prompt
    (domain/description/hints) come from the ACTIVE seed, so a different seed just works."""
    # candidates are INPUT LEAVES ONLY — never a subtotal/total/net or a carry-leaf, so a TB amount can
    # never be offered a derived/carry line as a target.
    carry = master_store.carry_leaf_ids()
    candidates = [c.canonical_concept for c in master_store.concepts.values()
                  if c.kind == "leaf" and c.concept_id not in carry]
    return propose_master_mappings(items, candidates, system=_assemble_master_system(master_store),
                                   entity_noun=master_store.prompts().get("entity_noun", "entity"),
                                   client=client)


# ---- ARCHETYPE DETECTION (sibling proposer): which registered seed does this TB match? -------------
# Generic system prompt — the candidate charts (ids/domains/vocabularies) are DATA in the user prompt, so
# no archetype literal lives here. LABELS/CODES ONLY; the model returns per-label FIT, never a score.
_ARCHETYPE_SYSTEM = (
    "You are the ARCHETYPE DETECTOR of an auditable financial-statement generator. You are given a trial "
    "balance's account LABELS (and codes) — NEVER any amount — and several candidate MASTER CHARTS, each "
    "with a domain and its line vocabulary. For EACH trial-balance label, say which chart(s) it is "
    "consistent with — a label 'fits' a chart if that chart genuinely has a line for it. Rules:\n"
    "1. A label that fits MULTIPLE charts (e.g. 'Cash', 'Accounts receivable') is GENERIC — list every "
    "chart it fits. A label that fits EXACTLY ONE chart is DISCRIMINATING — it names a line that only "
    "that one domain's chart carries. Judge fit from each chart's listed lines below.\n"
    "2. A label that fits NO candidate chart -> fits=[].\n"
    "3. Read the LABEL — never a code, never an amount. Do NOT output any score or confidence number.\n"
    "4. Also, for EACH chart, list a few of its SIGNATURE lines that are ABSENT from this trial balance.\n"
    "5. Output EXACTLY one JSON object: {\"per_label\":[{\"label\":..,\"fits\":[chart_id,..],\"evidence\":..}],"
    "\"absent\":{chart_id:[line,..]}}"
)


def _fingerprints(stores, registry) -> dict:
    """Labels-only fingerprint per registered seed: {id: {label, domain, entity_noun, leaves}}."""
    out = {}
    for sid, store in stores.items():
        out[sid] = {"label": (registry.get(sid, {}) or {}).get("label", sid),
                    "domain": store.prompts().get("domain", ""),
                    "entity_noun": store.prompts().get("entity_noun", ""),
                    "leaves": [c.canonical_concept for c in store.concepts.values() if c.kind == "leaf"]}
    return out


def propose_archetype(items, stores, *, client=None, thresholds=None):
    """items: (code, label). stores: {seed_id: MasterStructureStore} for EVERY registered seed. Returns an
    ArchetypeProposal — a PROPOSAL, never auto-confirmed. The model does labels-only per-label fit; the
    score (discriminating-label fraction) and the conservative verdict are computed deterministically."""
    from ai_accountant.llm.client import LLMClient
    from ai_accountant.master_fs.detect import archetype_verdict
    from ai_accountant.master_fs.seed import load_detect_thresholds, load_registry
    client = client or LLMClient()
    thresholds = thresholds or load_detect_thresholds()
    fps = _fingerprints(stores, load_registry())
    charts = "\n".join(f"- id: {sid} | domain: {fp['domain']} | lines: " + "; ".join(fp["leaves"])
                       for sid, fp in fps.items())
    rows = "\n".join(f"{code}\t{label}" for code, label in items)
    prompt = (f"Candidate master charts:\n{charts}\n\n"
              f"Trial-balance lines (code <tab> label) — LABELS ONLY, no amounts:\n{rows}")
    raw = client.complete_json(prompt, system=_ARCHETYPE_SYSTEM)
    per_label = [p for p in raw.get("per_label", []) if isinstance(p, dict)]
    absent = raw.get("absent", {}) if isinstance(raw.get("absent"), dict) else {}
    return archetype_verdict(per_label, absent, items, fps, thresholds)


# ---- MATURITY SPLIT (sibling proposer): classify a movement line / facility CURRENT vs NON-CURRENT ----
# Generic IAS 1 / IFRS 9 reasoning frame — a FRAMEWORK invariant (applies to every archetype), no archetype
# or concept literal. LABELS ONLY; the proposer outputs a CLASSIFICATION, never an amount. Weak/no maturity
# signal -> 'unsure' (no 50/50, no proportional default — code never manufactures a split).
_MATURITY_SYSTEM = (
    "You classify trial-balance / GL movement-line LABELS as CURRENT or NON-CURRENT for financial-statement "
    "presentation — LABELS ONLY, never amounts. Apply IAS 1: a liability/asset is CURRENT if due to be "
    "settled/realised within twelve months of the reporting date, or the entity has no unconditional right "
    "to defer settlement beyond twelve months; otherwise NON-CURRENT. For financial instruments, IFRS 9 "
    "classification reasoning applies. Rules:\n"
    "1. Read the LABEL only — maturity captions, tenors, 'due within one year', 'current portion', a stated "
    "settlement year. NEVER an amount, and you must NOT ask for one.\n"
    "2. If the label gives NO maturity signal, return maturity='unsure' — do NOT guess, do NOT default to a "
    "50/50 or any proportional split. Being unsure is correct; a manufactured split is the worst outcome.\n"
    "3. Cite the exact label words that drove the call; confidence high | medium | low.\n"
    "4. Output EXACTLY one JSON object: {\"proposals\":[{\"code\":..,\"maturity\":\"current|non_current|unsure\","
    "\"confidence\":\"high|medium|low\",\"evidence\":..}]}"
)


@dataclass
class MaturitySplitProposal:
    code: str
    label: str
    maturity: str                       # "current" | "non_current" | "unsure"
    confidence: str
    evidence: str

    @property
    def is_confident(self) -> bool:
        return self.maturity in ("current", "non_current") and self.confidence != "low"


def propose_maturity_split(items, *, client=None) -> list:
    """items: (code, label) of a note's movement lines / facilities. Classifies each CURRENT vs NON-CURRENT
    (or 'unsure') from LABELS ONLY — pinned model, IAS 1/IFRS 9 frame, NO amounts. Weak signal -> unsure
    (which the caller turns into a BLOCK; code never manufactures a split)."""
    from ai_accountant.llm.client import LLMClient
    client = client or LLMClient()
    rows = "\n".join(f"{code}\t{label}" for code, label in items)
    prompt = ("Movement lines / facilities (code <tab> label) — LABELS ONLY, no amounts:\n" + rows
              + "\n\nClassify each CURRENT vs NON-CURRENT, or 'unsure' if the label gives no maturity signal.")
    raw = client.complete_json(prompt, system=_MATURITY_SYSTEM)
    by = {str(p.get("code", "")).strip(): p for p in raw.get("proposals", []) if isinstance(p, dict)}
    out = []
    for code, label in items:
        p = by.get(code, {})
        out.append(MaturitySplitProposal(code=code, label=label, maturity=str(p.get("maturity", "unsure")),
                                         confidence=str(p.get("confidence", "low")),
                                         evidence=str(p.get("evidence", ""))))
    return out


# ---- STATIC BREAKDOWN (sibling proposer — DEMOTED to a fallback): group a concept's sub-accounts ----
# Used ONLY when the TB carries no usable level hierarchy under the concept (the deterministic levels path is
# tried first). The AI proposes the GROUPING (which sub-accounts go together) — NEVER a leaf label (the
# builder always uses the sub-account's own TB label) and NEVER an amount. For a multi-leaf group that has no
# source name, it MAY propose a caption, which lands in C2 as an AI proposal a human must confirm — never
# auto-applied. So the AI keeps its grouping judgment for unclean sources, but cannot author presentation.
_STATIC_SYSTEM = (
    "You group the sub-accounts of ONE financial-statement line into a few presented COMPONENT groups for a "
    "note breakdown, when their labels don't already organise themselves. You are given each sub-account's "
    "code and LABEL only — NEVER an amount, and you must NOT ask for one. Rules:\n"
    "1. Every sub-account must go into EXACTLY ONE group (a complete, non-overlapping partition) — never drop "
    "one, never place one twice. A sub-account that fits no group stays on its own.\n"
    "2. You decide only the GROUPING (which codes go together). You may suggest a caption for a multi-code "
    "group, but it is only a SUGGESTION a human will confirm — do NOT rename a single sub-account.\n"
    "3. Do NOT compute, sum, or invent any figure.\n"
    "4. Output EXACTLY one JSON object: {\"components\":[{\"accounts\":[code,..],\"caption\":..}]}"
)


def propose_static_breakdown(items, *, hints=None, client=None) -> list:
    """items: (account, label) of ONE concept's mapped sub-accounts. Returns account GROUPINGS ONLY —
    [{accounts:[...], caption?}] — never leaf labels, never amounts (pinned model). Deterministic floor =
    one group per distinct TB label (`group_by_label`). The LLM may regroup + suggest a multi-code caption,
    accepted ONLY if it is a complete, disjoint partition of exactly these accounts; else the floor is kept.
    The CALLER (the builder) derives every leaf label from the TB; an AI caption is human-confirmed in C2."""
    from ai_accountant.master_fs.notes import group_by_label
    accounts = [a for a, _l in items]
    labels = {a: l for a, l in items}
    base = group_by_label({a: 0.0 for a in accounts}, labels)
    if client is None or len(accounts) <= 1:
        return base
    rows = "\n".join(f"{a}\t{l}" for a, l in items)
    hint = f"\nSuggested group captions (optional): {', '.join(hints)}" if hints else ""
    raw = client.complete_json(f"Sub-accounts (code <tab> label) — LABELS ONLY:\n{rows}{hint}",
                               system=_STATIC_SYSTEM)
    proposed = []
    for c in raw.get("components", []) if isinstance(raw, dict) else []:
        if not isinstance(c, dict):
            continue
        accts = [str(a) for a in c.get("accounts", []) if str(a) in accounts]
        if accts:                                          # caption is a SUGGESTION only (multi-leaf); no leaf labels
            proposed.append({"accounts": accts, "caption": (str(c["caption"]) if c.get("caption") else None)})
    flat = [a for c in proposed for a in c["accounts"]]
    if proposed and set(flat) == set(accounts) and len(flat) == len(accounts):   # valid partition only
        return proposed
    return base                                             # non-partition → keep the deterministic floor


# ---- NOTE-AGENDA SURVEY (Slice S3c): the AI surveys the TB structure and PROPOSES which notes it supports.
# STRUCTURE ONLY — labels, leaf COUNTS, tier labels, and a per-leaf +/- SIGN FLAG. NEVER a monetary amount
# (the sign is structure; the value never leaves code). The AI guides the AGENDA; the engine re-derives every
# figure and renders BUILT only if it FOOTS — the AI authors neither a number nor a status.
def agenda_payload(master_store, mapping_store, client_id, tb_amounts, account_levels=None) -> list:
    """Build the survey payload: per POPULATED LEAF concept → {concept_id, label, leaf_count, leaves:[{label,
    sign}], levels:[tier labels]}. `sign` is '+'/'-' from the amount's sign (a FLAG); the amount itself is
    NEVER included. This is the discrete object the no-magnitude payload test asserts on every run."""
    account_levels = account_levels or {}
    mapping = mapping_store.mapping(client_id)
    by_concept: dict = {}
    for rec in mapping.values():
        if rec.concept_id and rec.account in tb_amounts:
            by_concept.setdefault(rec.concept_id, []).append((rec.account, rec.client_label))
    out = []
    for cid, accts in by_concept.items():
        c = master_store.get(cid)
        if c is None or c.is_computed:                          # leaves only — never a computed total
            continue
        leaves = [{"label": str(lbl or a), "sign": ("+" if tb_amounts.get(a, 0.0) >= 0 else "-")}
                  for a, lbl in accts]
        levels = []
        for a, _lbl in accts:
            for lv in (account_levels.get(a) or []):
                if str(lv).strip() and str(lv) not in levels:
                    levels.append(str(lv))
        out.append({"concept_id": str(cid), "label": str(c.canonical_concept),
                    "leaf_count": len(accts), "leaves": leaves, "levels": levels})
    return out


_AGENDA_SYSTEM = (
    "You SURVEY a trial balance's account structure and propose which financial-statement NOTES it can "
    "support. Per FS-line concept you are given: its label, its sub-account labels, a +/- SIGN FLAG per "
    "sub-account (NEVER an amount — you are given none and must not ask), the sub-account COUNT, and the "
    "tier/level labels. Propose:\n"
    "1. buildable — concepts whose sub-accounts compose a note the TB can support (a multi-sub-account "
    "breakdown; a cost layer with a NEGATIVE accumulated-depreciation layer → a net-book-value note; a gross "
    "with a NEGATIVE allowance → a net-of-allowance note).\n"
    "2. not_buildable — with a short reason (a single sub-account → nothing to break down; a movement/roll-"
    "forward note → needs a GL not present in a trial balance).\n"
    "3. semantic_material — whether a reader of the statements expects a note for this line (a major caption "
    "vs a trivial / rounding bucket). This is JUDGMENT on the LABEL, not on any amount.\n"
    "You propose the AGENDA only — you NEVER compute, sum, or invent a figure. Output EXACTLY one JSON "
    "object: {\"buildable\":[concept_id],\"not_buildable\":[{\"concept_id\":..,\"reason\":..}],"
    "\"semantic_material\":{concept_id:true|false}}"
)


def propose_note_agenda(payload, *, client=None) -> dict:
    """Given the structure-only `agenda_payload`, the LIVE model proposes the note agenda — buildable /
    not-buildable(reason) / semantic-material. Returned ids are SANITISED to the payload's concepts (a
    hallucinated id is dropped); a buildable note that doesn't actually foot is BLOCKED by the engine, not
    here. Labels + signs + counts only ever reach the model; pinned client (no demo stub for the survey)."""
    import json
    from ai_accountant.llm.client import LLMClient
    client = client or LLMClient()
    ids = {c["concept_id"] for c in payload}
    raw = client.complete_json("Concept structures (labels + sub-account labels + +/- sign flags + counts + "
                               "tier labels — NO amounts):\n" + json.dumps(payload, ensure_ascii=False),
                               system=_AGENDA_SYSTEM)
    raw = raw if isinstance(raw, dict) else {}
    buildable = [str(x) for x in raw.get("buildable", []) if str(x) in ids]
    not_buildable = [{"concept_id": str(b.get("concept_id")), "reason": str(b.get("reason", ""))}
                     for b in raw.get("not_buildable", []) if isinstance(b, dict) and str(b.get("concept_id")) in ids]
    semantic = {str(k): bool(v) for k, v in (raw.get("semantic_material", {}) or {}).items() if str(k) in ids}
    return {"buildable": buildable, "not_buildable": not_buildable, "semantic_material": semantic}


# ---- MATURITY PAIRING (AI-FALLBACK sibling, Slice B2a): pair current/non-current halves the deterministic
# alias-matcher couldn't cleanly pair. Runs ONLY on the ambiguous remainder (not the deterministic build
# path). LABELS ONLY, never amounts; an AI-proposed pairing is AI_ASSUMED until a human confirms it.
_PAIRING_SYSTEM = (
    "You pair financial-statement concept LABELS into the current / non-current halves of the SAME line item "
    "— only when an automatic name-match could not. You are given concept labels, each tagged its maturity "
    "side (nc | c). You are NEVER given amounts and must NOT ask for one. Rules:\n"
    "1. Pair EXACTLY one non-current concept with EXACTLY one current concept that are genuinely the two "
    "halves of the same item (e.g. 'Borrowings — non-current' with 'Current portion of borrowings').\n"
    "2. Leave a label UNPAIRED if you are not confident — do NOT force a pairing; a wrong pairing is worse "
    "than an unpaired one.\n"
    "3. Output EXACTLY one JSON object: {\"pairings\":[{\"non_current\":id,\"current\":id}]}"
)


def propose_maturity_pairing(candidates, *, client=None) -> list:
    """candidates: (concept_id, label, side) with side in {'nc','c'} — the maturity-halves the deterministic
    matcher left unpaired. Proposes [(nc_id, c_id)] pairings, LABELS ONLY, pinned model, no amounts. Each
    proposed pair is validated to be exactly one nc + one c from the candidate set; an unconfident model
    (no/partial pairings) leaves halves unpaired (→ the build guard flags them). Human confirms before use."""
    if client is None or not candidates:
        return []
    ids_nc = {cid for cid, _l, s in candidates if s == "nc"}
    ids_c = {cid for cid, _l, s in candidates if s == "c"}
    rows = "\n".join(f"{cid}\t{lbl}\t{side}" for cid, lbl, side in candidates)
    raw = client.complete_json("Concepts to pair (id <tab> label <tab> side):\n" + rows, system=_PAIRING_SYSTEM)
    out, used = [], set()
    for p in raw.get("pairings", []) if isinstance(raw, dict) else []:
        nc, c = str(p.get("non_current", "")), str(p.get("current", ""))
        if nc in ids_nc and c in ids_c and nc not in used and c not in used:   # one nc + one c, each once
            out.append((nc, c))
            used.update({nc, c})
    return out


def confirm_archetype(proposal, chosen_seed_id, *, approver, at, audit=None, registry_path=None) -> str:
    """Human-confirm one level up — REQUIRES an explicit chosen_seed_id (no default). Reuses the
    AI_ASSUMED->AI_CONFIRMED provenance: confirming the proposed seed is AI_CONFIRMED; picking a different
    registered seed (incl. after an UNSURE block) is a 'preparer_override'. Returns the confirmed seed_id."""
    from ai_accountant.master_fs.seed import load_registry
    if chosen_seed_id not in load_registry(registry_path):
        raise ValueError(f"chosen_seed_id {chosen_seed_id!r} is not a registered master")
    prov = AI_CONFIRMED if (proposal.verdict == "propose" and chosen_seed_id == proposal.seed_id) else "preparer_override"
    if audit is not None:
        audit.log(AuditRecord(action="confirm_archetype", target=chosen_seed_id, client_id="",
                              provenance=prov, confidence="", approver=approver, at=at,
                              detail=f"verdict={proposal.verdict} block={proposal.block_reason}"))
    return chosen_seed_id


def apply_mapping_decisions(proposals, master_store, *, client_id, decisions, mapping_store, audit,
                            approver, at) -> None:
    """decisions: account → 'confirm' (human reviewed) | 'assume' (accepted unverified) | else open.
    Confirm → AI_CONFIRMED (BUILT-eligible); assume → AI_ASSUMED (flagged, never BUILT); unsure / not
    confident / not decided → UNMAPPED + flagged (never force-mapped to the nearest-looking concept)."""
    for p in proposals:
        decision = (decisions or {}).get(p.code, "open")
        concept = master_store.by_canonical(p.line) if (p.line and p.line.strip().lower() != "unsure") else None
        if concept is not None and (concept.is_computed or concept.concept_id in master_store.carry_leaf_ids()):
            mapping_store.put(client_id, MappingRecord(           # BLOCK — never place an amount on a derived/carry line
                account=p.code, concept_id=None, client_label=p.label, provenance="", confidence=p.confidence,
                flagged_reason=f"amount mapped to computed/carry concept {concept.concept_id} — left open",
                master_id=master_store.master_id))
            continue
        if concept is None or not p.is_confident or decision not in ("confirm", "assume"):
            reason = ("unsure — no confident concept" if (concept is None or not p.is_confident)
                      else "left open by reviewer")
            mapping_store.put(client_id, MappingRecord(
                account=p.code, concept_id=None, client_label=p.label, provenance="",
                confidence=p.confidence, flagged_reason=reason, master_id=master_store.master_id))
            continue
        provenance = AI_CONFIRMED if decision == "confirm" else AI_ASSUMED
        mapping_store.put(client_id, MappingRecord(
            account=p.code, concept_id=concept.concept_id, client_label=p.label, provenance=provenance,
            confidence=p.confidence, approver=approver, approved_at=at, master_id=master_store.master_id))
        audit.log(AuditRecord("map_account", p.code, client_id, provenance, p.confidence, approver, at,
                              detail=f"-> {concept.concept_id}"))


# ---- propose-ADDITION: a line no concept covers → a new master concept with a coherent placement ----
@dataclass
class ProposedConcept:
    canonical: str
    statement: str
    l0_section: str           # AI-proposed section (the human confirms the placement)
    l1_group: "str | None"
    confidence: str
    evidence: str


def _section_from_classification(classification: str, statement: str, master_store) -> str:
    """Match a free-text classification to one of the statement's DECLARED sections (generic token
    match), falling back to the seed's declared default placement — no literal section names."""
    c = _norm(classification)
    for sec in master_store.sections(statement):
        toks = [t.rstrip("s") for t in re.split(r"[_\s]+", sec.lower()) if len(t) >= 3]
        if any(t[:5] in c for t in toks):
            return sec
    dp = master_store.default_placement()
    if dp.get("statement") == statement and dp.get("section") in master_store.sections(statement):
        return dp["section"]
    secs = master_store.sections(statement)
    return secs[0] if secs else ""


# GENERIC extension prompt template — the statement/section ENUMS and the example captions come from the
# ACTIVE seed (no archetype name or section literal here). For the original seed it reproduces the prompt.
_EXTENSION_TEMPLATE = (
    "A <<ENTITY>> trial-balance line matched NO existing master financial-statement concept. Decide, "
    "from the LABEL only (never amounts), whether it is a GENUINE new FS face line that should be ADDED "
    "to the master, or NOT a face line that must stay an open finding (never invented onto the "
    "statements). Rules:\n"
    "1. If it is a real asset / liability / equity / income / expense / OCI caption missing from the "
    "master (e.g. <<EXAMPLES>>), set is_face_line=true and give: a concise canonical name; the statement "
    "(<<STATEMENTS>>); and the section (<<SECTIONS>>).\n"
    "2. If it is NOT a face line — a suspense / clearing / control / inter-branch / rounding / temporary "
    "account — set is_face_line=false; it stays an open finding for a human, NEVER added.\n"
    "3. Be conservative: only propose an addition for a clear, genuine FS line. Cite the label words; "
    "confidence high | medium | low.\n"
    "4. Output EXACTLY one JSON object: {\"proposals\":[{\"account\":..,\"is_face_line\":true/false,"
    "\"canonical\":..,\"statement\":..,\"section\":..,\"confidence\":\"high|medium|low\",\"evidence\":..}]}"
)


def _assemble_extension_system(master_store) -> str:
    p = master_store.prompts()
    return (_EXTENSION_TEMPLATE.replace("<<ENTITY>>", p.get("entity_noun", "entity"))
            .replace("<<EXAMPLES>>", p.get("extension_examples", ""))
            .replace("<<STATEMENTS>>", " | ".join(master_store.statement_keys()))
            .replace("<<SECTIONS>>", " | ".join(master_store.all_sections_ordered())))


@dataclass
class ExtensionDecision:
    account: str
    label: str
    is_face_line: bool
    canonical: str
    statement: str
    l0_section: str
    confidence: str
    evidence: str


def propose_master_extensions(items, master_store, *, client=None) -> list:
    """items: (account, label) for lines that matched no concept. The AI decides per line: ADD a new
    master concept (is_face_line, canonical, statement, section) or leave it as an open finding. Live,
    labels-only. Conservative — junk/suspense stays a finding, never invented onto the statements."""
    from ai_accountant.llm.client import LLMClient
    client = client or LLMClient()
    rows = "\n".join(f"{a}\t{lbl}" for a, lbl in items)
    prompt = ("Lines that matched no master concept (account <tab> label) — LABELS ONLY:\n" + rows
              + "\n\nFor each, decide: add as a new master face line, or leave as an open finding.")
    raw = client.complete_json(prompt, system=_assemble_extension_system(master_store))
    by = {str(p.get("account", "")).strip(): p for p in raw.get("proposals", []) if isinstance(p, dict)}
    dp = master_store.default_placement()
    out = []
    for a, lbl in items:
        p = by.get(a, {})
        is_face = bool(p.get("is_face_line", False))
        statement = str(p.get("statement", dp.get("statement", "")))
        section = str(p.get("section", dp.get("section", "")))
        if is_face and (statement not in master_store.statement_keys()
                        or section not in master_store.sections(statement)):
            is_face = False                                # placement not a declared section → keep as finding
        out.append(ExtensionDecision(
            account=a, label=lbl, is_face_line=is_face,
            canonical=str(p.get("canonical", lbl)), statement=statement, l0_section=section,
            confidence=str(p.get("confidence", "low")), evidence=str(p.get("evidence", ""))))
    return out


def propose_master_extension(account, label, statement, master_store, *, client=None) -> ProposedConcept:
    """Reuse `propose_seed_mapping` to read the LABEL → a classification → the proposed section. The
    new line's canonical IS the (cleaned) label; the section is the AI's proposal for WHERE it sits."""
    candidates = [c.canonical_concept for c in master_store.statement(statement)]
    p = propose_seed_mapping([(account, label)], candidates, client=client)[0]
    return ProposedConcept(canonical=re.sub(r"\s+", " ", str(label).strip()), statement=statement,
                           l0_section=_section_from_classification(p.classification, statement, master_store),
                           l1_group=None, confidence=p.confidence, evidence=p.evidence)


def confirm_master_extension(proposed, master_store, *, concept_id, approver, at, audit, client_id,
                             l0_section=None, l1_group=None, order=None) -> MasterConcept:
    """Human confirms the placement (section + order) → append to the master. Structure only."""
    section = l0_section or proposed.l0_section
    placed_order = order if order is not None else master_store.next_order(proposed.statement, section)
    concept = MasterConcept(
        concept_id=concept_id, statement=proposed.statement, l0_section=section,
        l1_group=l1_group if l1_group is not None else proposed.l1_group,
        canonical_concept=proposed.canonical, label_aliases={}, presence="client_added",
        order=placed_order, provenance="proposed_confirmed")
    master_store.add(concept)
    audit.log(AuditRecord("extend_master", concept_id, client_id, "proposed_confirmed",
                          proposed.confidence, approver, at, detail=f"{section} @ order {placed_order}"))
    return concept
