"""Slice B2b — the cross-sheet reconcile FIREWALL for the balance-sheet current/non-current split.

A TB whose coarse mapping lumps a concept on ONE maturity half (the B2a "split undetermined" case) can be
SPLIT using the published balance sheet — but only behind a reconcile firewall: the BS split must agree
with the TB's lumped total, or two source documents disagree and it FLAGS (never silently picks one or
overwrites the TB). The TB stays the anchor; the BS split is an override layer (Approach B).

Pure + deterministic (no store, no I/O) → unit-testable branch-by-branch. Four branches per
current/non-current pair `(nc, c)`:

  1. BS split present AND BOTH years reconcile (nc+c == the TB lumped total, current AND prior, within tol)
     → APPLY: emit an override for both halves. Balance-neutral (Σ == the anchor it replaces).
  2. BS split present AND it disagrees (either year off) → KEEP the lumped total + flag 'undetermined'
     + a 'disagree' finding. NO half-apply: if one year ties and the other doesn't, the WHOLE pair flags.
  3. BS split present AND there is NO TB anchor (concept absent from the TB) → INJECT but mark
     'uncorroborated' (shown, never reading as reconciled) + a 'no_anchor' finding. The caller re-runs the
     balance check on the post-override totals (a BS-only injection can unbalance the SOFP → its own flag).
  4. No BS split for the pair → unchanged B2a: flag 'undetermined' if exactly one side is populated.
"""
from __future__ import annotations

_TOL = 0.005


def _pop(cid, leaf_cur, leaf_pri):
    return abs(leaf_cur.get(cid, 0.0)) >= _TOL or abs(leaf_pri.get(cid, 0.0)) >= _TOL


def _v(cell, period):
    return (cell or {}).get(period) or 0.0


def reconcile_face_split(pairs, leaf_cur, leaf_pri, face_amounts, *, tol: float = _TOL) -> dict:
    """pairs: [(nc_id, c_id)] (clean + human-confirmed maturity pairs). leaf_cur/leaf_pri: {concept_id ->
    RAW (pre-override) leaf amount} for each period — the TB ANCHOR. face_amounts: {concept_id -> {current,
    prior}} from the BS sheet ({} when no split was supplied). Returns:
        {"override": {cid: {current, prior}},   # branch 1 (reconciled) + branch 3 (uncorroborated) — apply
         "undetermined": {cid},                  # B2a flag retained (branch 2 + branch 4)
         "uncorroborated": {cid},                # branch 3 — injected without a TB anchor (loud marker)
         "findings": [(concept_id, kind, message)]}  # kind ∈ undetermined | disagree | no_anchor
    No amount is scaled — only compared (a unit mismatch surfaces as a 'disagree')."""
    override: dict = {}
    undetermined: set = set()
    uncorroborated: set = set()
    findings: list = []
    face_amounts = face_amounts or {}

    for nc, c in pairs:
        amt_nc, amt_c = face_amounts.get(nc), face_amounts.get(c)
        has_face = amt_nc is not None or amt_c is not None
        pop_nc, pop_c = _pop(nc, leaf_cur, leaf_pri), _pop(c, leaf_cur, leaf_pri)

        if not has_face:                                       # ---- branch 4: no BS split → B2a flag-only
            if pop_nc != pop_c:
                pid = nc if pop_nc else c
                undetermined.add(pid)
                findings.append((pid, "undetermined",
                                 "current/non-current split not determinable from this trial balance — the "
                                 "split is disclosed in the BS/notes, not the TB; the total is shown unsplit"))
            continue

        sum_cur = round(_v(amt_nc, "current") + _v(amt_c, "current"), 2)
        sum_pri = round(_v(amt_nc, "prior") + _v(amt_c, "prior"), 2)

        if pop_nc or pop_c:                                  # a TB anchor exists for this pair
            anchor_cur = round(leaf_cur.get(nc, 0.0) + leaf_cur.get(c, 0.0), 2)   # the TB's lumped pair total
            anchor_pri = round(leaf_pri.get(nc, 0.0) + leaf_pri.get(c, 0.0), 2)
            cur_ok = abs(sum_cur - anchor_cur) < tol
            pri_ok = abs(sum_pri - anchor_pri) < tol
            if cur_ok and pri_ok:                            # ---- branch 1: BOTH years tie → APPLY
                override[nc] = {"current": _v(amt_nc, "current"), "prior": _v(amt_nc, "prior")}
                override[c] = {"current": _v(amt_c, "current"), "prior": _v(amt_c, "prior")}
            else:                                            # ---- branch 2: disagree (or only one year) → flag
                undetermined.add(nc if pop_nc else c)
                gaps = []
                if not cur_ok:
                    gaps.append(f"current Σ {sum_cur:,.2f} ≠ TB {anchor_cur:,.2f}")
                if not pri_ok:
                    gaps.append(f"prior Σ {sum_pri:,.2f} ≠ TB {anchor_pri:,.2f}")
                findings.append((nc if pop_nc else c, "disagree",
                                 "BS-sheet split disagrees with the trial balance — not applied, shown unsplit ("
                                 + "; ".join(gaps) + ")"))
        else:                                                # ---- branch 3: no TB anchor → inject + mark loud
            injected = False
            for side, cell in ((nc, amt_nc), (c, amt_c)):
                if cell is not None and (_v(cell, "current") or _v(cell, "prior")):
                    override[side] = {"current": cell.get("current"), "prior": cell.get("prior")}
                    uncorroborated.add(side)
                    injected = True
            if injected:
                findings.append((nc, "no_anchor",
                                 "from BS sheet — NOT reconciled to any trial-balance amount (no TB anchor for "
                                 "this concept); shown but uncorroborated"))

    return {"override": override, "undetermined": undetermined,
            "uncorroborated": uncorroborated, "findings": findings}
