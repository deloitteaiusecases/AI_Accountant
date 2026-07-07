"""Seed-driven validation — load-time `engine`-block integrity and authored-rollup fidelity.

These run for ANY seed and reference NO archetype facts (statement keys, sections, concept_ids, alias
column names all come from the seed/args). The bank-approved-xlsx / CSV reconciliation (which necessarily
names the xlsx's two bank alias columns) lives separately in `gate0.py`, since it only runs for a
seed that ships an approved xlsx and is not part of the seed-driven runtime path.
"""
from __future__ import annotations

import json
from pathlib import Path


def validate_engine_meta(seed: dict) -> list:
    """Load-time guard: the seed's `engine` block must be internally consistent. A dangling id or a
    section that drifts from the concepts is a BLOCK (the loader raises), never a silent skip."""
    eng = seed.get("engine")
    if not eng:
        return ["no `engine` block — the seed must declare its own structural roles"]
    statements = seed.get("statements", {})
    all_ids = {c["concept_id"] for rows in statements.values() for c in rows}
    problems: list = []

    declared = [s.get("key") for s in eng.get("statements", [])]
    if declared != list(statements.keys()):
        problems.append(f"engine.statements keys {declared} != concept statement keys {list(statements.keys())}")

    for s in eng.get("statements", []):
        key = s.get("key")
        rows = sorted(statements.get(key, []), key=lambda x: int(x["order"]))
        present, seen = [], set()
        for c in rows:
            if c["l0_section"] not in seen:
                seen.add(c["l0_section"]); present.append(c["l0_section"])
        if list(s.get("sections", [])) != present:
            problems.append(f"[{key}] declared sections {s.get('sections')} != sections present {present}")
        for cid in s.get("coverage_totals", []):
            if cid not in all_ids:
                problems.append(f"[{key}] coverage_total {cid!r} is not a concept in this seed")

    bc = eng.get("balance_check")
    if bc:
        for k in ("assets_total", "liab_equity_total"):
            if bc.get(k) not in all_ids:
                problems.append(f"balance_check.{k} {bc.get(k)!r} is not a concept in this seed")
    for cid in eng.get("memo_leaves", []):
        if cid not in all_ids:
            problems.append(f"memo_leaf {cid!r} is not a concept in this seed")

    # COMPONENT INTEGRITY — a bad id inside a concept's roll-up would silently contribute 0 to a
    # subtotal/total; catch it at load (every component is a ['+'|'-', existing concept_id] pair).
    for rows in statements.values():
        for c in rows:
            for comp in c.get("components", []):
                if (not isinstance(comp, (list, tuple)) or len(comp) != 2
                        or comp[0] not in ("+", "-") or comp[1] not in all_ids):
                    problems.append(f"concept {c.get('concept_id')!r} has invalid component {comp!r} "
                                    f"(must be ['+' or '-', a concept_id existing in this seed])")

    # CARRY-LEAVES — a leaf populated from another concept's derived value (no AI). id must exist and be
    # a leaf; `from` must exist; the carry graph (source statement -> target statement) must be acyclic.
    kind_of = {c["concept_id"]: c.get("kind", "leaf") for rows in statements.values() for c in rows}
    stmt_of = {c["concept_id"]: c["statement"] for rows in statements.values() for c in rows}
    edges = []
    for cl in eng.get("carry_leaves", []):
        cid, frm = cl.get("id"), cl.get("from")
        if cid not in all_ids:
            problems.append(f"carry_leaf id {cid!r} is not a concept in this seed")
        elif kind_of.get(cid) != "leaf":
            problems.append(f"carry_leaf id {cid!r} must be kind=leaf (is {kind_of.get(cid)!r})")
        if frm not in all_ids:
            problems.append(f"carry_leaf from {frm!r} is not a concept in this seed")
        if cid in stmt_of and frm in stmt_of:
            edges.append((stmt_of[frm], stmt_of[cid]))            # source-stmt -> target-stmt
    # cycle detection over the statement-level carry graph
    adj: dict = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}

    def _has_cycle(n):
        color[n] = GREY
        for m in adj.get(n, []):
            if color.get(m, WHITE) == GREY or (color.get(m, WHITE) == WHITE and _has_cycle(m)):
                return True
        color[n] = BLACK
        return False
    if any(color.get(n, WHITE) == WHITE and _has_cycle(n) for n in list(adj)):
        problems.append("carry_leaves form a cycle across statements (would not converge)")

    # RESULT_CLOSE (Slice I1) — the seed-declared current-year-result → retained close. retained_concept
    # must be a leaf (a mappable equity line); result_total must be a computed concept (the SCI total).
    rc = eng.get("result_close")
    if rc:
        rcid, rtot = rc.get("retained_concept"), rc.get("result_total")
        if rcid not in all_ids:
            problems.append(f"result_close.retained_concept {rcid!r} is not a concept in this seed")
        elif kind_of.get(rcid) != "leaf":
            problems.append(f"result_close.retained_concept {rcid!r} must be kind=leaf (is {kind_of.get(rcid)!r})")
        if rtot not in all_ids:
            problems.append(f"result_close.result_total {rtot!r} is not a concept in this seed")
        elif kind_of.get(rtot) == "leaf":
            problems.append(f"result_close.result_total {rtot!r} must be a computed total (is a leaf)")

    dp = eng.get("default_placement", {})
    if dp.get("statement") not in declared:
        problems.append(f"default_placement.statement {dp.get('statement')!r} is not a declared statement")
    else:
        secs = next((s.get("sections", []) for s in eng["statements"] if s["key"] == dp.get("statement")), [])
        if dp.get("section") not in secs:
            problems.append(f"default_placement.section {dp.get('section')!r} not in {dp.get('statement')} sections")

    # NOTES — a face concept declaring a seed-driven note breakdown. concept & anchor must exist and be
    # leaves (face lines); mechanism must be one the engine knows. Fail loud at load.
    # contra_ecl: a recognised-but-not-yet-built mechanism (the gross-balance + ECL-allowance variant). A
    # face concept may DECLARE it; the engine renders it 'not generated — mechanism not yet built' (never
    # forced through the roll-forward builder, never faked).
    _MECHANISMS = ("roll_forward", "static_breakdown", "calculation", "contra_ecl", "register")
    _MATURITY = ("current", "non_current")
    for nt in eng.get("notes", []):
        if nt.get("mechanism") not in _MECHANISMS:
            problems.append(f"note mechanism {nt.get('mechanism')!r} not in {_MECHANISMS}")
        if "splits" in nt:                                  # a one-total → N-concepts split note
            mats = []
            for sp in nt.get("splits", []):
                cid = sp.get("concept")
                if cid not in all_ids:
                    problems.append(f"note split concept {cid!r} is not a concept in this seed")
                elif kind_of.get(cid) != "leaf":
                    problems.append(f"note split concept {cid!r} must be a leaf/face line (is {kind_of.get(cid)!r})")
                if sp.get("maturity") not in _MATURITY:
                    problems.append(f"note split maturity {sp.get('maturity')!r} not in {_MATURITY}")
                mats.append(sp.get("maturity"))
            if len(nt.get("splits", [])) < 2 or len(set(mats)) < 2:
                problems.append(f"note {nt.get('note')!r} splits must cover ≥2 distinct maturities")
        elif nt.get("mechanism") == "static_breakdown":     # Slice S1 — a no-GL component breakdown
            # SEED declares mechanism + caption (+ optional label hints) ONLY; the component leaves are
            # PER-CLIENT TB accounts, so the complete+disjoint PARTITION is the BUILD-time firewall, never load.
            cid = nt.get("concept")
            if cid not in all_ids:
                problems.append(f"static_breakdown concept {cid!r} is not a concept in this seed")
            elif kind_of.get(cid) != "leaf":
                problems.append(f"static_breakdown concept {cid!r} must be a leaf/face line (is {kind_of.get(cid)!r})")
            if not (isinstance(nt.get("caption"), str) and nt.get("caption", "").strip()):
                problems.append(f"static_breakdown note on {cid!r} must declare a non-empty caption")
            if "component_hints" in nt and not (isinstance(nt["component_hints"], list)
                                                and all(isinstance(x, str) for x in nt["component_hints"])):
                problems.append(f"static_breakdown component_hints {nt.get('component_hints')!r} must be a list of strings")
        elif nt.get("mechanism") == "register":             # SL-1c.1 — register enrichment (concept + caption only;
            cid = nt.get("concept")                         # the register rows are EXTERNAL data, tied at build time)
            if cid not in all_ids:
                problems.append(f"register concept {cid!r} is not a concept in this seed")
            elif kind_of.get(cid) != "leaf":
                problems.append(f"register concept {cid!r} must be a leaf/face line (is {kind_of.get(cid)!r})")
            if not (isinstance(nt.get("caption"), str) and nt.get("caption", "").strip()):
                problems.append(f"register note on {cid!r} must declare a non-empty caption")
        else:                                               # a single-concept note (N0 / N1)
            for key in ("concept", "anchor"):
                cid = nt.get(key)
                if cid not in all_ids:
                    problems.append(f"note {key} {cid!r} is not a concept in this seed")
                elif kind_of.get(cid) != "leaf":
                    problems.append(f"note {key} {cid!r} must be a leaf/face line (is {kind_of.get(cid)!r})")
            # OPTIONAL movement-note vocab (Slice N1): a caption (the note's own title) and the set of
            # classes exempt from the contra (e.g. land / goodwill). Typed-checked, never inferred.
            if "caption" in nt and not (isinstance(nt["caption"], str) and nt["caption"].strip()):
                problems.append(f"note caption {nt.get('caption')!r} must be a non-empty string")
            if "exempt_classes" in nt and not (isinstance(nt["exempt_classes"], list)
                                               and all(isinstance(x, str) for x in nt["exempt_classes"])):
                problems.append(f"note exempt_classes {nt.get('exempt_classes')!r} must be a list of strings")
            for k in ("cost_config", "contra_config", "builder"):   # Slice N2 movement-note build hints
                if k in nt and not (isinstance(nt[k], str) and nt[k].strip()):
                    problems.append(f"note {k} {nt.get(k)!r} must be a non-empty string")

    pr = eng.get("prompts", {})
    for k in ("domain", "master_desc", "entity_noun", "mapping_hints", "extension_examples"):
        if not pr.get(k):
            problems.append(f"prompts.{k} missing/empty (the mapping prompt cannot be assembled)")
    return problems


def validate_rollups(json_path, rollups_path) -> list:
    """Prove the seed faithfully carries the HUMAN-AUTHORED roll-up formulas (kind + signed components),
    so the derive pass computes exactly what was authored — the AI never authored these. Mirror of the
    JSON↔xlsx discipline, for the kind/components structure that lives only in the JSON."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    authored = json.loads(Path(rollups_path).read_text(encoding="utf-8"))
    rollups = authored["rollups"]
    by_id = {r["concept_id"]: r for rows in data["statements"].values() for r in rows}
    problems: list = []

    def comps(x):
        return [list(c) for c in x]

    # every authored roll-up present in the seed with the authored kind + components, verbatim
    for cid, spec in rollups.items():
        jr = by_id.get(cid)
        if jr is None:
            problems.append(f"authored roll-up {cid!r} missing from seed")
            continue
        if jr.get("kind") != spec["kind"]:
            problems.append(f"{cid}: seed kind {jr.get('kind')!r} != authored {spec['kind']!r}")
        if comps(jr.get("components", [])) != comps(spec["components"]):
            problems.append(f"{cid}: seed components != authored components")

    # the four required additions exist
    for cid in authored.get("must_add_to_seed", []):
        if cid not in by_id:
            problems.append(f"required addition {cid!r} not added to seed")

    # no ROGUE computed concept — every kind!=leaf in the seed must be an authored roll-up
    for cid, jr in by_id.items():
        if jr.get("kind", "leaf") != "leaf" and cid not in rollups:
            problems.append(f"seed concept {cid!r} is computed (kind={jr.get('kind')!r}) but not authored")

    # leaf set agreement — authored leaves and seed leaves must be the same concept_ids
    seed_leaves = {cid for cid, jr in by_id.items() if jr.get("kind", "leaf") == "leaf"}
    authored_leaves = {l["concept_id"] for l in authored.get("leaves", [])}
    for cid in sorted(authored_leaves - seed_leaves):
        problems.append(f"authored leaf {cid!r} not a leaf in the seed")
    for cid in sorted(seed_leaves - authored_leaves):
        problems.append(f"seed leaf {cid!r} not in the authored leaf list")
    return problems

