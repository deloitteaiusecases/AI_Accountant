"""Deterministic derive pass — compute every net / subtotal / total from the human-authored signed
component formulas carried on the master concepts. Runs BETWEEN mapping and render.

THE AI/ARITHMETIC BOUNDARY: leaves are populated by mapped TB accounts (AI may map them); every
computed line here is PURE ARITHMETIC over those leaves and is owned end-to-end by this engine — the AI
never authors a formula and never touches a total. Sign convention: the TB stores expenses/zakat/tax
NEGATIVE, so net-lines use "+" on already-negative values (e.g. Net operating income = Total operating
income + Total operating expenses, the latter being negative).

Two guards live here, because this is where a silently-wrong total could be born:
  * orphan guard  — every populated leaf must fall inside a total's TRANSITIVE component closure;
                    an orphan is surfaced (finding), never silently excluded.
  * balance check — Total assets vs Total liabilities and equity; a mismatch is a non-blocking finding
                    (a TB with unmapped suspense legitimately won't balance — the difference is signal).
"""
from __future__ import annotations

_EPS = 0.005
# Coverage totals, memo leaves, and the balance-check ids are SEED-DECLARED (store.meta) — no literals
# here, so a new archetype's derive/guards work with zero engine-code changes.


def _sign(s) -> float:
    return -1.0 if str(s) == "-" else 1.0


def topo_order(store, statement) -> list:
    """Computed concepts of a statement in dependency order (a concept after all the concepts it
    references). Deterministic — ties broken by `order`. Raises on a cycle (authored data is acyclic)."""
    computed = {c.concept_id: c for c in store.statement(statement) if c.is_computed}
    out, temp, done = [], set(), set()

    def visit(cid):
        if cid in done or cid not in computed:
            return
        if cid in temp:
            raise ValueError(f"cycle in roll-up formulas at {cid!r}")
        temp.add(cid)
        for _sgn, dep in sorted(computed[cid].components):
            visit(dep)
        temp.discard(cid)
        done.add(cid)
        out.append(cid)

    for cid in sorted(computed, key=lambda c: computed[c].order):
        visit(cid)
    return out


def derive_statement(store, statement, leaf_amounts: dict, *, sign_overrides: dict = None):
    """leaf_amounts: {concept_id -> summed amount} for POPULATED leaves only.
    Returns (values, present): values includes leaves + every computed concept; present is the set of
    concept_ids that should render (populated leaves, present intermediates, and ALL spine totals).
    `sign_overrides` (Slice S6a): {component concept_id -> '+'/'-'} a PER-TB, human-confirmed correction to a
    component's roll-up sign (a mis-signed contra, e.g. treasury stored negative under a subtracting formula).
    The leaf AMOUNT is untouched (the line still presents its stored sign); only the total's sign is corrected."""
    sign_overrides = sign_overrides or {}
    values = dict(leaf_amounts)
    present = {cid for cid, amt in leaf_amounts.items() if amt is not None and abs(amt) >= _EPS}
    for cid in topo_order(store, statement):
        c = store.get(cid)
        total = sum(_sign(sign_overrides.get(dep, sgn)) * values.get(dep, 0.0) for sgn, dep in c.components)
        values[cid] = round(total, 2)
        if c.kind == "total" or any(dep in present for _sgn, dep in c.components):
            present.add(cid)                   # spine total always present; intermediate iff a component is
    return values, present


def apply_carries(store, by_concept: dict) -> dict:
    """Populate each SEED-DECLARED carry-leaf from its `from` concept's DERIVED value (e.g. OCI's
    net-income line carried from the P&L net-profit total) — deterministic, no AI, no amounts. The
    source is a computed total, so we derive its statement first, then inject; statements are visited in
    carry-dependency order (validated acyclic at load). The carry-leaf is the line's sole populator
    (the mapper blocks any TB amount from landing on it)."""
    carries = store.carry_leaves()
    if not carries:
        return by_concept
    out = dict(by_concept)
    src_stmts: list = []
    for c in carries:
        s = store.get(c.get("from"))
        if s is not None and s.statement not in src_stmts:
            src_stmts.append(s.statement)
    dep = {s: set() for s in src_stmts}                     # source stmt X depends on Y if X has a carry fed from Y
    for c in carries:
        tgt, frm = store.get(c.get("id")), store.get(c.get("from"))
        if tgt is not None and frm is not None and tgt.statement in dep and frm.statement in src_stmts:
            dep[tgt.statement].add(frm.statement)
    ordered, seen = [], set()

    def _visit(s):
        if s in seen:
            return
        seen.add(s)
        for d in dep.get(s, ()):
            _visit(d)
        ordered.append(s)
    for s in src_stmts:
        _visit(s)

    for stmt in ordered:
        vals, _ = derive_statement(store, stmt, out)
        for c in carries:
            frm = store.get(c.get("from"))
            if frm is not None and frm.statement == stmt and c.get("from") in vals:
                out[c["id"]] = round(vals[c["from"]], 2)
    return out


def _leaf_closure(store, cid, acc):
    """Transitive set of LEAF concept_ids reachable from `cid` through the component graph."""
    c = store.get(cid)
    if c is None:
        return
    if not c.is_computed:
        acc.add(cid)
        return
    for _sgn, dep in c.components:
        _leaf_closure(store, dep, acc)


def coverage_leaves(store, statement) -> set:
    """Every leaf transitively covered by the statement's SEED-DECLARED coverage total(s) — the
    TRANSITIVE walk is the point: gross leaves reach the spine total via the net-lines/subtotals."""
    acc: set = set()
    for total_id in store.coverage_totals(statement):
        if store.get(total_id) is not None:
            _leaf_closure(store, total_id, acc)
    return acc


def orphan_leaves(store, statement, populated_leaf_ids) -> list:
    """Populated leaves outside every coverage total's closure (and not declared memos in the seed).
    Such a leaf would render but go uncounted — an understated total. Surfaced, never silently dropped."""
    covered = coverage_leaves(store, statement)
    memo = store.memo_leaves()
    return sorted(cid for cid in populated_leaf_ids if cid not in covered and cid not in memo)


def balance_difference(store, values: dict):
    """The seed's balance check (e.g. Total assets − Total liabilities and equity). None if the seed
    declares no balance_check or either declared total is absent from `values`."""
    bc = store.balance_check()
    if not bc:
        return None
    a, le = bc.get("assets_total"), bc.get("liab_equity_total")
    if a not in values or le not in values:
        return None
    return round(values[a] - values[le], 2)


def diagnose_balance(store, statement, leaf_amounts: dict, diff, *, tol: float = _EPS) -> list:
    """Slice S6a — DETERMINISTIC balance-failure diagnosis (no AI, no model). When a statement is off by `diff`,
    find a mis-signed CONTRA: a leaf that rolls up with a SUBTRACTING sign ('-') and a non-zero value (so the
    formula flips its stored sign — the double-negation signature), whose sign-FLIP ('-'→'+') makes the balance
    re-derive to zero. STRUCTURAL — iterates the seed's component graph, no concept literal. Returns candidates
    carrying ONLY structure + sign-flags + a small-int multiple (no SAR amount — so Slice S6b can hand it to the
    model). The caller proposes the SINGLE clean candidate, DEFERS on >1 (never guesses), and stays flagged on 0."""
    if not store.balance_check() or diff is None or abs(diff) < tol:
        return []
    suspects: dict = {}                                      # leaf concept_id → '-' (it is SUBTRACTED in some total)
    for c in store.statement(statement):
        if not c.is_computed:
            continue
        for sgn, dep in c.components:
            d = store.get(dep)
            if str(sgn) == "-" and d is not None and not d.is_computed:
                suspects[dep] = "-"
    cands = []
    for cid in suspects:
        val = leaf_amounts.get(cid, 0.0)
        if abs(val) < tol:
            continue
        vals, _ = derive_statement(store, statement, leaf_amounts, sign_overrides={cid: "+"})
        flipped = balance_difference(store, vals)
        if flipped is not None and abs(flipped) < tol:       # flipping '-'→'+' makes the SOFP balance
            c = store.get(cid)
            contribution = -val                              # the subtracting formula's contribution (= _sign('-')·val)
            cands.append({"concept_id": cid, "label": (c.canonical_concept if c else cid),
                          "formula_sign": "-", "stored_sign": ("-" if val < 0 else "+"), "corrected_sign": "+",
                          "flip_cancels": True,
                          "imbalance_multiple": (round(diff / contribution) if abs(contribution) >= tol else None)})
    return cands
