"""Note-attachment seam for the master-FS path — re-anchor an EXISTING note builder to a master concept.

A face concept declares (in the seed) that it has a note (`engine.notes`). The note is built from an
uploaded GL by the GL-free note builder (`master_fs.notelib.ppe.build_ppe_note`), and reconciles
to THE MASTER CONCEPT'S VALUE OR BLOCKS — via an injected `LineRecon` whose target is the concept's
computed value. No archetype/concept literal lives here: the concept id is read from the seed and passed
in. The roll-forward's sign convention is asserted EXPLICITLY here (it is not asserted inside the builder).

KNOWN LIMITATION (documented, bounded): the anchor reconciles the GL note's TOTAL to the concept's value
("whole-concept total-to-total" attribution). A concept fed by MANY TB leaves where only some are
GL-covered can reconcile in aggregate while the per-leaf split is wrong. The N0 synthetic fixture keeps the
concept to one/two leaves; fine-grained GL-class → TB-leaf attribution is a NAMED refinement that must be
resolved before any multi-leaf note rides this pattern (see documentation.md / NOTES_PHASE_ROADMAP.md).
"""
from __future__ import annotations

_EPS = 0.005


def concept_anchor(master_store, mapping_store, client, tb_amounts, concept_id, gl_by_leaf,
                   *, scale: float = 1.0, tol: float = _EPS):
    """A `LineRecon` with REAL per-leaf attribution. `gl_by_leaf` maps each concept-leaf TB account → the
    GL amount attributed to THAT leaf (GL units); `scale` is the GL→concept unit ratio. The gap is computed
    on the COVERED subtotal (uncovered leaves excluded from BOTH sides), so an uncovered leaf can never
    contribute to a reconciliation — it surfaces as `uncovered_leaves` / `status()=="PARTIAL"`."""
    from ai_accountant.master_fs.notelib.recon import LineRecon, TBAccount

    mapped = {rec.account: round(tb_amounts.get(rec.account, 0.0), 2)
              for rec in mapping_store.mapping(client).values()
              if rec.concept_id == concept_id and rec.account in tb_amounts}
    leaves = [TBAccount(code=a, level="L4", account_type="C", label="", final_amount=amt, raw_amount=amt)
              for a, amt in mapped.items()]
    # real per-leaf GL (scaled); only leaves the GL actually attributes to are "covered"
    gl_by_code = {a: round(v / scale, 2) for a, v in gl_by_leaf.items() if a in mapped}
    return LineRecon(caption=concept_id, leaves_on_line=leaves, gl_by_code=gl_by_code, tol=tol)


def note_status(anchor) -> str:
    """The note's coverage status, queryable distinct from a generic 'has findings': BUILT (reconciles +
    fully covered) | PARTIAL (reconciles but a leaf is uncovered) | BLOCKED (covered subtotal ≠ GL)."""
    return anchor.status() if anchor is not None else "—"


def note_findings(concept_id, anchor, caption="note") -> list:
    """Turn a note's `LineRecon` into master-FS findings (so it can't sit silently on the anchor): a
    BLOCKED covered-subtotal gap, or a PARTIAL coverage finding listing the uncovered leaves. `caption`
    labels the finding (the note's own caption, e.g. 'Property, plant and equipment')."""
    st = note_status(anchor)
    if st == "BLOCKED":
        return [(f"note:{concept_id}", caption,
                 f"note does not reconcile to the concept (covered gap {anchor.gap:,.2f}) — BLOCKS")]
    if st == "PARTIAL":
        uncovered = [l.code for l in anchor.uncovered_leaves]
        return [(f"note:{concept_id}", caption,
                 f"note covers {anchor.coverage_pct}% of the concept's leaves; UNCOVERED (GL not provided): "
                 f"{uncovered} — PARTIAL, not a complete breakdown")]
    return []


def assert_sign_convention(note, convention) -> list:
    """EXPLICIT sign check (independent of the anchor): every accumulated-CONTRA closing must carry the
    recorded contra direction. Reads the MECHANISM field `contra_closing`/`has_contra` (so it works for
    PP&E's depreciation, intangibles' amortization, or any later contra), keyed on the mechanism-level
    convention `accumulated_contra` — the contra-negative direction is universal across them. A violation
    is a BLOCKING finding; an UNRECORDED convention is a flag (magnitude-unverified on sign), never assumed."""
    if not convention:
        return ["sign convention not recorded for this client — accumulated-contra direction "
                "unverified; the note is magnitude-unverified on sign (flagged, never assumed)"]
    direction = convention.get("accumulated_contra", "contra_negative")
    out = []
    for s in note.sections:
        if s.has_contra and direction == "contra_negative" and s.contra_closing > _EPS:
            out.append(f"accumulated-contra sign disagrees with recorded convention for "
                       f"{s.asset_class!r} (closing {s.contra_closing:,.2f} > 0; expected contra-negative) — BLOCKS")
    return out


def record_sign_convention(client, *, accumulated_contra="contra_negative",
                           disposals="reduces_balance", approver="", at="", audit=None) -> dict:
    """Record the per-client sign convention at confirm time (stored alongside the mapping result), with
    provenance. The note seam asserts against this; it is never assumed. The contra direction is recorded
    at the MECHANISM level (`accumulated_contra`) — one direction is correct for depreciation, amortization
    and any later contra."""
    conv = {"accumulated_contra": accumulated_contra, "disposals": disposals,
            "recorded_by": approver, "at": at}
    if audit is not None:
        from ai_accountant.master_fs.model import AuditRecord
        audit.log(AuditRecord(action="record_sign_convention", target=client, client_id=client,
                              provenance="preparer", confidence="", approver=approver, at=at, detail=str(conv)))
    return conv


_JUDGMENT_MARKER = "current/non-current split is a management judgment; no independent verification"


def detect_split_case(mapping_store, client, tb_amounts, split_concepts) -> str:
    """'A' = every split concept is INDEPENDENTLY populated in the TB (a GL-independent backstop);
    'B' = the split is disclosure-only (the TB does not carry both halves) — judgment-only."""
    from ai_accountant.master_fs.render import leaf_amounts
    v = leaf_amounts(mapping_store, client, tb_amounts)
    return "A" if all(abs(v.get(c, 0.0)) >= _EPS for c in split_concepts) else "B"


def apply_split(line_amounts, classification, splits) -> dict:
    """CODE owns the arithmetic: sum the movement-line amounts by the CONFIRMED classification into each
    split concept (mapped by the seed-declared maturity tag). The AI supplied only the classification."""
    by_maturity = {sp["maturity"]: sp["concept"] for sp in splits}
    portions = {sp["concept"]: 0.0 for sp in splits}
    for code, amt in line_amounts.items():
        concept = by_maturity.get(classification.get(code))
        if concept is not None:
            portions[concept] = round(portions[concept] + amt, 2)
    return portions


def record_maturity_split(client, note, classification, *, approver="", at="", audit=None) -> dict:
    """Record the AI-proposed maturity classification (NOT an amount), provenance AI_ASSUMED — mirrors
    `record_sign_convention` but WITH the propose→confirm layer. The statement stays not_final until
    `confirm_split` flips it."""
    from ai_accountant.master_fs.model import AI_ASSUMED, AuditRecord
    rec = {"note": note, "classification": dict(classification), "provenance": AI_ASSUMED,
           "recorded_by": approver, "at": at}
    if audit is not None:
        audit.log(AuditRecord(action="record_maturity_split", target=note, client_id=client,
                              provenance=AI_ASSUMED, confidence="", approver=approver, at=at,
                              detail=f"classification={classification}"))
    return rec


def confirm_split(split_record, *, approver="", at="", audit=None) -> dict:
    """The UN-BYPASSABLE engine gate: flip AI_ASSUMED → AI_CONFIRMED. not_final is derived from this
    provenance (not a GUI flag), so a direct engine caller cannot skip it."""
    from ai_accountant.master_fs.model import AI_CONFIRMED, AuditRecord
    split_record = dict(split_record)
    split_record["provenance"] = AI_CONFIRMED
    if audit is not None:
        audit.log(AuditRecord(action="confirm_split", target=split_record.get("note", ""), client_id="",
                              provenance=AI_CONFIRMED, confidence="", approver=approver, at=at,
                              detail="classification confirmed"))
    return split_record


def attach_split_note(master_store, mapping_store, client, tb_amounts, note_decl, note_total,
                      line_amounts, split_record, *, scale: float = 1.0, tol: float = _EPS) -> dict:
    """Reconcile a one-total → N-concepts split. Case A: Σ-check + per-concept TB backstop (BLOCK on
    disagreement). Case B: judgment-only (never reconciled, persistent marker). Unsure → BLOCK, no split."""
    from ai_accountant.master_fs.model import AI_CONFIRMED
    from ai_accountant.master_fs.render import leaf_amounts
    splits = note_decl["splits"]
    split_concepts = [sp["concept"] for sp in splits]
    note = note_decl.get("note", "split")
    confirmed = split_record.get("provenance") == AI_CONFIRMED
    classification = split_record.get("classification", {})
    case = detect_split_case(mapping_store, client, tb_amounts, split_concepts)

    unclassified = [c for c in line_amounts if classification.get(c) not in ("current", "non_current")]
    if unclassified:                                        # unsure → BLOCK, never guessed
        return {"note": note, "case": case, "status": "BLOCKED", "portions": {}, "judgment_marker": None,
                "split_concepts": split_concepts, "confirmed": confirmed,
                "findings": [(f"split:{note}", "maturity split",
                              f"unclassified / unsure movement line(s) {unclassified} — no split, BLOCKS (never guessed)")]}

    portions = apply_split(line_amounts, classification, splits)
    v = leaf_amounts(mapping_store, client, tb_amounts)
    findings = []
    if case == "A":
        sigma_v = round(sum(v.get(c, 0.0) for c in split_concepts), 2)
        gaps = []
        if abs(round(note_total / scale, 2) - sigma_v) >= tol:
            gaps.append(f"note total {round(note_total/scale,2):,.2f} ≠ Σ concepts {sigma_v:,.2f}")
        for c in split_concepts:
            if abs(round(portions.get(c, 0.0) / scale, 2) - round(v.get(c, 0.0), 2)) >= tol:
                gaps.append(f"{c}: split {round(portions.get(c,0.0)/scale,2):,.2f} ≠ TB {round(v.get(c,0.0),2):,.2f}")
        if gaps:
            status = "BLOCKED"
            findings.append((f"split:{note}", "maturity split",
                             "AI split disagrees with the TB's independent current/non-current values — BLOCKS: "
                             + "; ".join(gaps)))
        elif not confirmed:
            status = "SPLIT_UNCONFIRMED"
            findings.append((f"split:{note}", "maturity split",
                             "split reconciles to the TB but is UNCONFIRMED (ai_assumed) — confirm to finalise"))
        else:
            status = "RECONCILED"
        return {"note": note, "case": "A", "status": status, "portions": portions, "judgment_marker": None,
                "split_concepts": split_concepts, "confirmed": confirmed, "findings": findings}

    # Case B — no GL-independent backstop: judgment-only, with a PERSISTENT marker (visible even confirmed)
    if not confirmed:
        status = "JUDGMENT_UNCONFIRMED"
        findings.append((f"split:{note}", "maturity split",
                         "split is a management judgment with NO independent backstop, ai_assumed — confirm "
                         "required; this can NEVER read as reconciled"))
    else:
        status = "JUDGMENT_CONFIRMED"               # confirmed clears not_final but the marker persists
    return {"note": note, "case": "B", "status": status, "portions": portions,
            "judgment_marker": _JUDGMENT_MARKER, "split_concepts": split_concepts,
            "confirmed": confirmed, "findings": findings}


# ---- STATIC BREAKDOWN (Slice S1): one concept → N component lines, summed from the concept's per-leaf
# TB amounts, grouped by an AI-proposed / human-confirmed labelling. NO GL, NO movement. The firewall is a
# PARTITION (complete + disjoint over the concept's mapped accounts), NOT a GL recon — orphan understates,
# double-count overstates; either BLOCKS at build. Σ(components) == concept BY CONSTRUCTION when it holds.
def _concept_mapped(mapping_store, client, concept_id, tb_amounts) -> "tuple[dict, dict]":
    """The TB accounts mapped to `concept_id` for this client → ({account: amount}, {account: client_label})."""
    amt, lbl = {}, {}
    for rec in mapping_store.mapping(client).values():
        if rec.concept_id == concept_id and rec.account in tb_amounts:
            amt[rec.account] = round(tb_amounts.get(rec.account, 0.0), 2)
            lbl[rec.account] = rec.client_label
    return amt, lbl


def _norm_lbl(s) -> str:
    import re
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _strip_quals(t) -> str:
    """The qualifier-strip CORE (normalisation-agnostic): given an ALREADY-NORMALISED label, strip a GENERIC
    set of trailing presentation qualifiers — a trailing parenthetical and a trailing ", net"/", gross" — then
    collapse whitespace. Shared so the breakdown anchor (S5a, under `_norm_lbl`) and the mapping resolver
    (S5a-resolve, under `resolve._norm`) reuse ONE qualifier rule, each with its own normaliser (no dash
    edge-case). NEVER strips the maturity suffix ("— current"/"— non-current") — that DISAMBIGUATES a pair."""
    import re
    t = re.sub(r"\s*\([^)]*\)\s*$", "", str(t))           # a trailing parenthetical: (SAMA), (net of allowance)
    t = re.sub(r",\s*(?:net|gross)\s*$", "", t)           # a trailing ", net" / ", gross"
    return re.sub(r"\s+", " ", t).strip()


def _strip_qual(s) -> str:
    """Slice S5a — `_strip_quals` under the breakdown-anchor normaliser (`_norm_lbl`). So a short level label
    anchors to its qualified canonical: "Investments" → "investments" == "Investments, net" stripped; "Cash and
    balances with the central bank" → "…(SAMA)" stripped. A BOUNDED normalization, NOT containment: "Other" stays
    "other" (≠ "other assets"), so it cannot over-match. Used ONLY as the Layer-1 fallback on an exact-match miss."""
    return _strip_quals(_norm_lbl(s))


def group_by_label(mapped: dict, labels: dict) -> list:
    """Identity/flat grouping: one ACCOUNT-GROUP per distinct client label (an unlabelled account is its own
    line). A complete, disjoint partition of `mapped` — the floor used when there are no usable TB levels and
    no AI grouping. Returns account groups ONLY (no presentation label — the builder derives labels)."""
    from collections import OrderedDict
    groups: "OrderedDict[str, list]" = OrderedDict()
    for a in mapped:
        groups.setdefault((str(labels.get(a) or "").strip()) or a, []).append(a)
    return [{"accounts": accts} for accts in groups.values()]


def _node(tier, source, children, lines):                  # a recursive breakdown node: children XOR (mostly) lines
    return {"tier": tier, "tier_source": source, "children": children, "lines": lines}


def _nested_subtotal_findings(node, concept_id, caption, has_prior, tol):
    """The PER-NODE partition assertion (Slice S4), recursive: at EVERY internal node, subtotal == Σ children
    (both years, within tol) — a mid-level subtotal that doesn't sum its children BLOCKS, not just top/bottom.
    On the build path subtotals are computed bottom-up so this is an invariant; it also guards any path that
    SUPPLIES subtotals. (It proves ARITHMETIC only — semantic tier membership stays the human-confirm's job.)"""
    kc = round(sum(c for _l, c, _p in node["lines"]) + sum(ch["subtotal"] for ch in node["children"]), 2)
    kp = round(sum((p or 0.0) for _l, _c, p in node["lines"]) + sum(ch["subtotal_prior"] for ch in node["children"]), 2)
    ok = abs(node["subtotal"] - kc) < tol and (not has_prior or abs(node["subtotal_prior"] - kp) < tol)
    bad = [] if ok else [(f"static:{concept_id}", caption,
                          f"subtotal {node['subtotal']:,.2f} ≠ Σ children {kc:,.2f} at tier "
                          f"'{node.get('tier')}' — BLOCKS")]
    for ch in node["children"]:
        bad += _nested_subtotal_findings(ch, concept_id, caption, has_prior, tol)
    return bad


def derive_breakdown(master_store, concept_id, mapped, labels, account_levels, *, client=None):
    """Decide the grouping by a HIERARCHY: (1) DETERMINISTIC from the TB level hierarchy — TWO tier levels (Slice
    S4): group by (below[0], below[1]) so a concept→classification→type→leaf renders nested subtotals; below[2:]
    flattens into the leaf, exactly as below[1:] did at one tier. (2) AI-FALLBACK groups the leaf accounts (account
    sets only, one-tier) when the source is flat/messy; (3) IDENTITY floor. Returns (nodes, path) where each node is
    `{tier, tier_source, children:[node…], lines:[{accounts…}]}`. SINGLE-LEAF-TIER COLLAPSE applies at EACH level
    (the S3a leaf-COUNT rule): a tier-2 with one leaf collapses flat into its tier-1; a tier-1 with one leaf
    collapses to tier=None — so existing one-tier notes (whose below[1] is unique per leaf) render byte-identical.
    Leaf labels are NEVER set here — the builder derives every leaf label from the TB (client_label); only a
    multi-leaf AI group may carry a caption (human-confirmed)."""
    from collections import OrderedDict
    concept = master_store.get(concept_id) if master_store else None
    names = ({_norm_lbl(concept.canonical_concept)} | {_norm_lbl(v) for v in concept.label_aliases.values()}
             if concept else set())
    stripped_names = {_strip_qual(n) for n in names}             # Layer-1 (S5a) — qualifier-stripped, computed once
    groups: "OrderedDict[object, OrderedDict]" = OrderedDict()    # tier1 → {tier2 → [accounts]} (order-preserving)
    any_tier = False
    for a in mapped:
        path = [str(x).strip() for x in (account_levels.get(a) or []) if str(x).strip()]
        # LAYERED ANCHOR: Layer 0 = exact normalized match (UNCHANGED — every existing note resolves here, so the
        # frozen-replay stays byte-identical); Layer 1 (S5a) = retry after stripping generic qualifiers, fired
        # ONLY on a Layer-0 miss (so "Investments" anchors to "Investments, net" without a model). No over-match.
        idx = next((i for i, v in enumerate(path) if _norm_lbl(v) in names), None)
        if idx is None:
            idx = next((i for i, v in enumerate(path) if _strip_qual(v) in stripped_names), None)
        below = path[idx + 1:] if idx is not None else []
        t1 = below[0] if len(below) >= 2 else None           # an intermediate level (not the deepest leaf) → tier-1
        t2 = below[1] if len(below) >= 2 else None            # a SECOND intermediate level → tier-2 (S4)
        any_tier = any_tier or t1 is not None
        groups.setdefault(t1, OrderedDict()).setdefault(t2, []).append(a)
    if any_tier:                                             # PATH 1 — deterministic from levels (now 2-deep)
        nodes = []
        for t1, t2map in groups.items():
            children, direct = [], []
            for t2, accts in t2map.items():
                if t2 is not None and len(accts) > 1:        # a REAL tier-2 grouping → keep its subtotal
                    children.append(_node(t2, "level", [],
                                          [{"accounts": [a], "caption_source": "leaf"} for a in accts]))
                else:                                        # single-leaf tier-2 → COLLAPSE, pull leaves to tier-1
                    direct.extend(accts)
            n_leaves = len(direct) + sum(len(ln["accounts"]) for ch in children for ln in ch["lines"])
            # tier-1 single-leaf collapse (the S3a rule, per level). Untiered leaves (t1 is None) keep today's
            # "Other" bucket label when there is more than one — byte-identical to the one-tier behaviour.
            label = (t1 if t1 is not None else "Other") if n_leaves > 1 else None
            nodes.append(_node(label, ("level" if label is not None else "none"), children,
                               [{"accounts": [a], "caption_source": "leaf"} for a in direct]))
        return (nodes, "levels")
    accounts = list(mapped)
    if client is not None and len(accounts) > 1:             # PATH 2 — AI-fallback grouping (account sets only)
        from ai_accountant.master_fs.mapping import propose_static_breakdown
        lines = []
        for g in propose_static_breakdown([(a, labels.get(a, "")) for a in accounts], client=client):
            accts = [a for a in g.get("accounts", []) if a in mapped]
            if accts:
                lines.append({"accounts": accts, "caption": g.get("caption"),
                              "caption_source": ("ai" if len(accts) > 1 and g.get("caption") else "leaf")})
        if lines:
            return ([_node(None, "none", [], lines)], "ai")
    return ([_node(None, "none", [],                         # PATH 3 — identity floor (each leaf its own line)
                   [{"accounts": [a], "caption_source": "leaf"} for a in accounts])], "identity")


def attach_static_breakdown(master_store, mapping_store, client, tb_amounts, concept_id, *, caption,
                            breakdown=None, account_levels=None, accepted=False, movement_pending=False,
                            prior_amounts=None, tol: float = _EPS) -> dict:
    """Build a static breakdown of `concept_id` from its per-leaf TB amounts, grouped via `derive_breakdown`
    (levels → AI-fallback → identity) or a human-confirmed `breakdown`. FIREWALLS (both paths): partition
    (complete + disjoint over the concept's mapped accounts), same-label-within-tier MERGE (lossless),
    Σtiers == concept. A LEAF LINE'S LABEL IS ALWAYS THE TB LABEL (client_label) — any label on the payload is
    IGNORED (rename-rejection); only a multi-leaf group may carry a caption (source level, or AI → must be
    human-confirmed → else GROUPING_UNCONFIRMED). Returns {"static": {...}}; the total carries the face tie."""
    from collections import OrderedDict
    mapped, labels = _concept_mapped(mapping_store, client, concept_id, tb_amounts)
    concept = master_store.get(concept_id) if master_store else None
    stmt_title = (master_store.statement_title(concept.statement) if (master_store and concept) else "")
    if not mapped:                                           # concept not populated by this TB → nothing to break down
        return {"static": {"concept": concept_id, "caption": caption, "tiers": [], "total": 0.0, "path": "none",
                           "status": "not generated", "accepted": accepted, "statement_title": stmt_title,
                           "face_value": 0.0, "findings": [], "reason": "concept not populated by this trial balance"}}
    account_levels = account_levels or {}
    if breakdown is not None:
        tiers, path = breakdown.get("tiers", []), breakdown.get("path", "confirmed")
    else:
        # the BUILD path is DETERMINISTIC (levels → identity); the AI-fallback grouping runs only in C2
        # (where a real LLM + a human review exist) and arrives here as a stored, confirmed `breakdown`.
        tiers, path = derive_breakdown(master_store, concept_id, mapped, labels, account_levels, client=None)

    has_prior = prior_amounts is not None                    # a comparative column was supplied for this TB
    mapped_prior = _concept_mapped(mapping_store, client, concept_id, prior_amounts)[0] if has_prior else {}
    ai_unconfirmed = False

    # RECURSIVE build (Slice S4): every subtotal is COMPUTED BOTTOM-UP from the mapped amounts, never read from the
    # input — so a subtotal can never disagree with Σ its children on this path; the per-node assertion below pins
    # that invariant. Same-label-within-NODE merge (lossless), leaf labels always from the TB (rename-rejection).
    def _build(dnode):
        nonlocal ai_unconfirmed
        bucket: "OrderedDict[str, list]" = OrderedDict()
        for ln in dnode.get("lines", []):
            accts = [a for a in ln.get("accounts", []) if a in mapped]
            if not accts:
                continue
            cur_amt = round(sum(mapped[a] for a in accts), 2)
            pri_amt = round(sum(mapped_prior.get(a, 0.0) for a in accts), 2)
            if len(accts) == 1:
                lbl = labels.get(accts[0]) or accts[0]       # LEAF label = TB label, NEVER from the payload
            elif ln.get("caption_source") in ("level", "confirmed"):
                lbl = ln.get("caption") or "?"               # a source-level / human-confirmed group caption
            else:                                            # AI-proposed caption for a multi-leaf group
                lbl = ln.get("caption") or "(unnamed group)"
                ai_unconfirmed = True                        # must be human-confirmed before BUILT
            cell = bucket.setdefault(lbl, [0.0, 0.0])
            cell[0] = round(cell[0] + cur_amt, 2)
            cell[1] = round(cell[1] + pri_amt, 2)
        lines = [(lbl, c, (p if has_prior else None)) for lbl, (c, p) in bucket.items()]
        children = [_build(ch) for ch in dnode.get("children", [])]
        sub = round(sum(c for _l, c, _p in lines) + sum(ch["subtotal"] for ch in children), 2)
        sub_p = round(sum((p or 0.0) for _l, _c, p in lines) + sum(ch["subtotal_prior"] for ch in children), 2)
        return {"tier": dnode.get("tier"), "subtotal": sub, "subtotal_prior": sub_p,
                "children": children, "lines": lines}

    rendered = [_build(d) for d in tiers]

    # NESTED PARTITION FIREWALL — fire at EVERY level. (a) LEAF partition complete + disjoint over ALL leaf-lines at
    # ANY depth; (b) PER-NODE subtotal == Σ children (both years) at every internal node — not just top/bottom (a
    # mid-level subtotal that doesn't sum its children BLOCKS, never silently passes); (c) grand == concept.
    # HONEST LIMIT (stated, not over-claimed): this proves the ARITHMETIC at every level. It does NOT and CANNOT
    # guarantee a leaf sits in the semantically-RIGHT tier under a confirmed/AI override — a mis-nested leaf with its
    # parent still summing right is invisible to arithmetic. On the deterministic path the tier IS the leaf's level
    # path (mechanical); on the confirmed/AI path the HUMAN confirms the grouping — unchanged from one tier.
    def _collect(dnode, acc):
        for ln in dnode.get("lines", []):
            acc.extend(a for a in ln.get("accounts", []) if a in mapped)
        for ch in dnode.get("children", []):
            _collect(ch, acc)
    assigned = []
    for d in tiers:
        _collect(d, assigned)
    orphaned = sorted(set(mapped) - set(assigned))
    seen, doubled = set(), set()
    for a in assigned:
        (doubled if a in seen else seen).add(a)

    rendered_findings = [f for d in rendered
                         for f in _nested_subtotal_findings(d, concept_id, caption, has_prior, tol)]
    findings = []
    total = round(sum(t["subtotal"] for t in rendered), 2)
    total_prior = round(sum(t["subtotal_prior"] for t in rendered), 2)
    concept_val = round(sum(mapped.values()), 2)             # == leaf_amounts for this concept (the face value)
    concept_val_prior = round(sum(mapped_prior.values()), 2)
    if orphaned:
        findings.append((f"static:{concept_id}", caption,
                         f"breakdown OMITS mapped leaf(s) {orphaned} — would understate the line; BLOCKS"))
    if doubled:
        findings.append((f"static:{concept_id}", caption,
                         f"breakdown DOUBLE-COUNTS leaf(s) {sorted(doubled)} — would overstate the line; BLOCKS"))
    findings += rendered_findings                            # per-node (mid-level) partition mismatches
    if abs(total - concept_val) >= tol:
        findings.append((f"static:{concept_id}", caption,
                         f"Σ breakdown {total:,.2f} ≠ concept {concept_val:,.2f} (current) — BLOCKS"))
    if has_prior and abs(total_prior - concept_val_prior) >= tol:    # BOTH-COLUMNS firewall — prior foots INDEPENDENTLY
        findings.append((f"static:{concept_id}", caption,
                         f"Σ breakdown {total_prior:,.2f} ≠ concept {concept_val_prior:,.2f} (PRIOR year) — BLOCKS"))
    if findings:
        status = "BLOCKED"
    elif accepted and not ai_unconfirmed:                    # valid + accepted (and no unconfirmed AI caption)
        status = "BUILT"
    else:
        status = "GROUPING_UNCONFIRMED"                      # foots, but grouping/caption not yet reviewed
    # OMIT-DON'T-ZERO: when this concept also declares a movement (roll-forward) but has no GL, the static
    # note shows CLOSING balances only and NAMES the absent movement — it never renders zero movement rows.
    movement_caveat = ("closing balances only — the cost/accumulated-depreciation MOVEMENT (opening → "
                       "additions → disposals → closing) needs a GL and is not generated"
                       if movement_pending and not findings else None)
    return {"static": {"concept": concept_id, "caption": caption, "path": path, "tiers": rendered,
                       "total": total, "face_value": concept_val, "statement_title": stmt_title,
                       "total_prior": (total_prior if has_prior else None),
                       "face_value_prior": (concept_val_prior if has_prior else None), "has_prior": has_prior,
                       "status": status, "accepted": accepted, "ai_caption_unconfirmed": ai_unconfirmed,
                       "movement_caveat": movement_caveat, "findings": findings}}


def attach_register_note(master_store, mapping_store, client, tb_amounts, concept_id, register, *,
                         caption, prior_amounts=None, tol: float = _EPS) -> dict:
    """Slice SL-1c.1 — a REGISTER-enriched note: carry the register's rows + attribute columns VERBATIM, and TIE
    its amount-column sum to the concept's TB face (the control-total firewall). The register is EXTERNAL to the
    TB, so `Σ register == face` is genuinely non-tautological — it PROVES the carried detail. Numbers are NEVER
    carried on trust: a sum that doesn't tie (scoped differently, partial, a unit slip) BLOCKS, never shows as
    reconciled. Attributes are pass-through — the engine owns ONLY the amounts + the tie. Contra rows (a negative
    'Less: Allowance' carrying value) net into the sum as signed rows, no literal. Both years independently.

    `register` is the `read_register` payload {columns, amount headers, rows[{label,cells,current,prior,section}]}.
    Returns {"register": {...}} consumed by `renderable_register`."""
    mapped, _labels = _concept_mapped(mapping_store, client, concept_id, tb_amounts)
    concept = master_store.get(concept_id) if master_store else None
    stmt_title = (master_store.statement_title(concept.statement) if (master_store and concept) else "")
    rows = register.get("rows", [])
    has_prior = prior_amounts is not None and any(r.get("prior") is not None for r in rows)
    concept_val = round(sum(mapped.values()), 2)
    concept_val_prior = (round(sum(_concept_mapped(mapping_store, client, concept_id, prior_amounts)[0].values()), 2)
                         if prior_amounts is not None else None)
    reg_sum = round(sum(r.get("current", 0.0) for r in rows), 2)
    reg_sum_prior = round(sum(r.get("prior") or 0.0 for r in rows), 2)

    # SECTION sub-totals (group rows by their section header, in first-seen order) — the per-node partition: the
    # sum of section sub-totals == the grand total (arithmetic, both years). Sections are the register's OWN
    # grouping (explicit 'A) …' rows), never inferred.
    from collections import OrderedDict
    by_sec: "OrderedDict[str, list]" = OrderedDict()
    for r in rows:
        by_sec.setdefault(r.get("section", "") or "", []).append(r)
    sections = [{"section": sec, "rows": rs,
                 "subtotal": round(sum(r.get("current", 0.0) for r in rs), 2),
                 "subtotal_prior": round(sum(r.get("prior") or 0.0 for r in rs), 2)}
                for sec, rs in by_sec.items()]

    blocking, caveat_notes = [], []                        # blocking → BLOCKED; caveat_notes → surfaced but BUILT
    if not rows:
        return {"register": {"concept": concept_id, "caption": caption, "columns": register.get("columns", []),
                             "sections": [], "rows": [], "total": 0.0, "face_value": concept_val,
                             "status": "not generated", "statement_title": stmt_title, "has_prior": False,
                             "reason": "register supplied no rows", "findings": []}}
    if abs(round(sum(s["subtotal"] for s in sections) - reg_sum, 2)) >= tol:
        blocking.append((f"register:{concept_id}", caption, "section sub-totals do not sum to the register total — BLOCKS"))
    if abs(reg_sum - concept_val) >= tol:                  # THE TIE — register Σ vs the TB face (current)
        blocking.append((f"register:{concept_id}", caption,
                         f"register Σ {reg_sum:,.2f} ≠ face {concept_val:,.2f} (current) — does not reconcile; BLOCKS"))
    if has_prior and concept_val_prior is not None and abs(reg_sum_prior - concept_val_prior) >= tol:
        blocking.append((f"register:{concept_id}", caption,
                         f"register Σ {reg_sum_prior:,.2f} ≠ face {concept_val_prior:,.2f} (PRIOR year) — BLOCKS"))

    # PER-ROW gross + allowance == net cross-check (SL-1c.2 — the contra-as-COLUMN case). Header-detected: runs
    # only when the register has a 'gross' AND an 'allowance/impairment' column for the CURRENT period; the engine
    # READS those numbers for a proof, never RE-DERIVES net (net is carried as given). A register without them
    # (Investment's contra is a ROW) skips this entirely. Numbers never on trust — even WITHIN the register.
    cols = register.get("columns", [])
    import re as _re
    from ai_accountant.tb_ingest.parse import _num as _pnum
    cyr = _re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", register.get("amount_current_header", "") or "")
    cyr = cyr.group(0) if cyr else None

    def _col(*kws, want_year=True):                        # the attribute column whose header matches a keyword (+ the current year)
        for i, h in enumerate(cols):
            hn = str(h).lower()
            if any(k in hn for k in kws) and (not want_year or not cyr or cyr in str(h)):
                return i
        return None
    g_i, a_i = _col("gross"), _col("allowance", "impairment", "provision")
    if g_i is not None and a_i is not None:
        bad = 0
        for r in rows:
            cl = r.get("cells", [])
            if g_i < len(cl) and a_i < len(cl):
                if abs(round(_pnum(cl[g_i]) + _pnum(cl[a_i]) - r.get("current", 0.0), 2)) >= tol:
                    bad += 1
        if bad:
            blocking.append((f"register:{concept_id}", caption,
                             f"{bad} row(s) where gross + allowance ≠ net — the register does not reconcile per facility; BLOCKS"))

    # PRIOR-YEAR honesty (SL-1c.2): a prior-period column carried as an ATTRIBUTE while there is NO prior tie
    # (the register provides no prior NET) → carried-not-reconciled. A CAVEAT, never a block — the current year ties.
    if not has_prior and cyr:
        prior_attr = [h for h in cols if (_m := _re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", str(h))) and _m.group(0) < cyr]
        if prior_attr:
            caveat_notes.append((f"register:{concept_id}", caption,
                                 "prior-year column(s) carried but NOT reconciled — the register provides no prior "
                                 "net to tie; the prior figure is shown for reference only"))
    findings = blocking + caveat_notes
    status = "BLOCKED" if blocking else "BUILT"
    return {"register": {"concept": concept_id, "caption": caption,
                         "columns": register.get("columns", []),
                         "amount_current_header": register.get("amount_current_header", "Amount"),
                         "amount_prior_header": register.get("amount_prior_header"),
                         "sections": sections, "rows": rows, "total": reg_sum,
                         "total_prior": (reg_sum_prior if has_prior else None), "face_value": concept_val,
                         "face_value_prior": (concept_val_prior if has_prior else None), "has_prior": has_prior,
                         "statement_title": stmt_title, "status": status, "findings": findings}}


def _attach_movement(master_store, mapping_store, client, tb_amounts, concept_id, build_fn,
                     *, attribution=None, sign_convention=None, scale: float = 1.0):
    """Shared two-pass attach: build once to read `nbv_by_class` (per-leaf attribution → anchor), then
    build again anchored, and assert the sign convention. `build_fn(anchor)` is the note builder (PP&E's
    adapter or the generic movement builder) — the seam is identical for every movement note."""
    pre = build_fn(None)
    mapped_leaves = [rec.account for rec in mapping_store.mapping(client).values()
                     if rec.concept_id == concept_id and rec.account in tb_amounts]
    if attribution is None:
        attribution = ({cls: mapped_leaves[0] for cls in pre.nbv_by_class} if len(mapped_leaves) == 1
                       else {})                                  # multi-leaf with NO attribution → all uncovered
    gl_by_leaf: dict = {}
    for cls, nbv in pre.nbv_by_class.items():
        leaf = attribution.get(cls)
        if leaf is not None:
            gl_by_leaf[leaf] = round(gl_by_leaf.get(leaf, 0.0) + nbv, 2)
    anchor = concept_anchor(master_store, mapping_store, client, tb_amounts, concept_id, gl_by_leaf, scale=scale)
    note = build_fn(anchor)
    return note, anchor, assert_sign_convention(note, sign_convention)


def attach_movement_note(master_store, mapping_store, client, tb_amounts, concept_id, leaves,
                         confirmed_structure, *, caption, exempt_classes=frozenset(), cost_config,
                         contra_config, attribution=None, sign_convention=None, presentation=None,
                         scale: float = 1.0):
    """Generic movement-note attach (Slice N1): build the two-layer roll-forward via `build_movement_note`
    (the vocabulary-free mechanism) with the note's `caption`/`exempt_classes`/configs, re-anchor to the
    master concept with REAL per-leaf attribution, and assert the sign convention. PP&E rides the thin
    `attach_ppe_note` wrapper below; intangibles (and the other roll-forward notes) ride this directly.
    Returns (note, anchor, sign_findings)."""
    from ai_accountant.master_fs.notelib.movement import build_movement_note
    return _attach_movement(
        master_store, mapping_store, client, tb_amounts, concept_id,
        lambda anchor: build_movement_note(leaves, confirmed_structure, caption=caption,
            exempt_classes=exempt_classes, cost_config=cost_config, contra_config=contra_config,
            anchor=anchor, presentation=presentation)[0],
        attribution=attribution, sign_convention=sign_convention, scale=scale)


class _GLLeaf:
    """A minimal roll-forward leaf for a supplied GL fixture (gl_account + opening/closing + movements)."""
    __slots__ = ("gl_account", "opening", "closing", "movement_by_ref")

    def __init__(self, gl_account, opening, closing, movement_by_ref=None):
        self.gl_account = gl_account
        self.opening = opening
        self.closing = closing
        self.movement_by_ref = dict(movement_by_ref or {})


def build_declared_notes(master_store, mapping_store, client, tb_amounts, gl, breakdowns=None,
                         account_levels=None, prior_amounts=None, agenda=None) -> dict:
    """Build every DECLARED note (engine.notes) the data supports. Movement notes through
    `attach_movement_note`/`attach_ppe_note` (need a GL payload); the maturity split through
    record→(confirm?)→attach; STATIC BREAKDOWNS from the concept's per-leaf TB amounts (NO GL) grouped by
    `breakdowns` (the human-confirmed per-client grouping {concept: [{label, accounts}]}) or a deterministic
    default. Returns `note_results` keyed by concept/note. A declared note with no data is left unbuilt (the
    export renders it 'not generated'). BUILDING ≠ CONFIRMING."""
    from ai_accountant.master_fs.notelib.propose import ConfirmedPPEAccount
    from ai_accountant.master_fs.notelib.note import Presentation
    from ai_accountant.master_fs.notelib.reference_codes import movement_config
    pres = Presentation(scale=1, confirmed=True)            # unit is explicit on the master-FS path (R11 satisfied)
    breakdowns = breakdowns or {}
    # concepts that ALSO declare a roll-forward movement — so a static build can name the absent movement
    movement_concepts = {d.get("concept") for d in master_store.notes() if d.get("mechanism") == "roll_forward"}
    static_decls = {d["concept"]: d for d in master_store.notes() if d.get("mechanism") == "static_breakdown"}
    results: dict = {}

    # STATIC pass — the AI AGENDA supersedes the seed static declarations on a real upload; with no agenda
    # (headless / fixtures) the seed-declared static set is the DETERMINISTIC FLOOR. Each concept is built at
    # most once; a concept that ALSO declares roll_forward with a GL payload steps aside (the movement builds
    # below) — the same exactly-one-branch-writes guarantee as the S3b GL-presence pick.
    static_concepts = list(dict.fromkeys(agenda)) if agenda is not None else list(static_decls)
    for concept in static_concepts:
        if gl and gl.get(concept) is not None:                  # GL → the roll-forward branch builds the movement
            continue
        c = master_store.get(concept)
        caption = (static_decls.get(concept, {}).get("caption")
                   or (c.canonical_concept if c else concept))
        res = attach_static_breakdown(master_store, mapping_store, client, tb_amounts, concept,
                                      caption=caption, breakdown=breakdowns.get(concept),
                                      accepted=(concept in breakdowns), account_levels=account_levels,
                                      prior_amounts=prior_amounts, movement_pending=(concept in movement_concepts))
        if res["static"]["status"] != "not generated":         # an unpopulated/empty concept stays 'not generated'
            results[concept] = res

    for decl in master_store.notes():
        if decl.get("mechanism") == "static_breakdown":         # handled by the agenda/floor pass above
            continue
        if decl.get("mechanism") == "register":                 # SL-1c.1 — a register-enriched note (gl[concept])
            key = decl.get("concept")
            payload = gl.get(key) if gl else None
            if payload is None:                                 # no register supplied → the coarse static note stands
                continue
            res = attach_register_note(master_store, mapping_store, client, tb_amounts, key, payload,
                                       caption=decl.get("caption", key), prior_amounts=prior_amounts)
            if res["register"]["status"] != "not generated":
                results[key] = res
            continue
        if "splits" in decl:                                    # one-total → N-concepts maturity split
            key = decl.get("note")
            payload = gl.get(key) if gl else None
            if payload is None:
                continue
            rec = record_maturity_split(client, key, payload["classification"],
                                        approver=payload.get("approver", ""), at=payload.get("at", ""))
            if payload.get("confirmed"):                        # ONLY on an explicit fixture confirmation
                rec = confirm_split(rec, approver=payload.get("approver", ""), at=payload.get("at", ""))
            res = attach_split_note(master_store, mapping_store, client, tb_amounts, decl,
                                    payload["note_total"], payload["line_amounts"], rec,
                                    scale=payload.get("scale", 1.0))
            results[key] = {"split": res}
            continue
        if decl.get("mechanism") != "roll_forward":             # only the roll-forward mechanism is built;
            continue                                            # contra_ecl/static/calculation → not generated
        key = decl.get("concept")                               # movement note
        payload = gl.get(key) if gl else None
        if payload is None:
            continue
        leaves = [_GLLeaf(d["gl_account"], d["opening"], d["closing"], d.get("movement_by_ref"))
                  for d in payload["leaves"]]
        confirmed = {a: ConfirmedPPEAccount(c, r, "fixture", payload.get("at", ""))
                     for a, (c, r) in payload["confirmed"].items()}
        sc = payload.get("sign_convention")
        if decl.get("builder") == "ppe":                        # PP&E adapter (keeps its voice byte-identical)
            note, anchor, sign = attach_ppe_note(master_store, mapping_store, client, tb_amounts, key, leaves,
                                                 confirmed, attribution=payload.get("attribution"),
                                                 sign_convention=sc, presentation=pres,
                                                 scale=payload.get("scale", 1.0))
        else:                                                   # generic movement note (configs seed-named)
            note, anchor, sign = attach_movement_note(
                master_store, mapping_store, client, tb_amounts, key, leaves, confirmed,
                caption=decl.get("caption", key), exempt_classes=set(decl.get("exempt_classes", [])),
                cost_config=movement_config(decl["cost_config"]),
                contra_config=movement_config(decl["contra_config"]),
                attribution=payload.get("attribution"), sign_convention=sc, presentation=pres,
                scale=payload.get("scale", 1.0))
        results[key] = {"note": note, "anchor": anchor, "sign_findings": sign, "caption": note.note_ref}
    return results


def attach_ppe_note(master_store, mapping_store, client, tb_amounts, concept_id, leaves,
                    confirmed_structure, *, attribution=None, sign_convention=None, presentation=None,
                    scale: float = 1.0):
    """PP&E specialisation: the same seam via the PP&E adapter builder (`build_ppe_note`), so the returned
    note keeps the PP&E field names (`missing_depreciation`, `total_accum_dep`, …). Byte-identical to N0.
    `attribution`: {asset_class → concept-leaf TB account}; default for a SINGLE-leaf concept = all classes
    → that leaf. Returns (note, anchor, sign_findings)."""
    from ai_accountant.master_fs.notelib.ppe import build_ppe_note
    return _attach_movement(
        master_store, mapping_store, client, tb_amounts, concept_id,
        lambda anchor: build_ppe_note(leaves, confirmed_structure, anchor=anchor, presentation=presentation)[0],
        attribution=attribution, sign_convention=sign_convention, scale=scale)
