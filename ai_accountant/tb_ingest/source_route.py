"""Slice SL-1 — the OPTIONAL `Source` note-routing accelerator, consumed as an OPAQUE key.

The decision (settled): the preparer's note tag ("Note 13", "Note 5(b)", "Note 15, 30", "Note 11.3") is DATA,
like a client label — it is PROPOSED-FROM and human-confirmed, NEVER matched against a hardcoded "Note 13"
literal in engine code or the seed. So this module assigns the engine NO meaning to any tag string; it only:
  * normalises a tag into its opaque group key(s) — compound ("Note 15, 30") → two memberships; a sub tag
    ("Note 15(a)", "Note 11.3") → its parent group ("note 15", "note 11") so sections of one note co-group;
  * CROSS-CHECKS the preparer's grouping against the engine's own concept-resolution and surfaces CONFLICTS
    (rows a tag groups together that resolve to DIFFERENT concepts; or one concept's rows carrying DIFFERENT
    tags) — a data-quality signal for the human, never an auto-pick.

NO hard dependency: with the Source column absent, `tb_rows` carry no tag → every function here is a no-op
and routing falls through to concept-resolution exactly as before. NO amounts are ever read here.
"""
from __future__ import annotations

import re


def parse_source_tag(tag: str) -> list:
    """A raw tag → its normalised opaque group key(s). Compound (comma/';'/'&') → multiple; a sub-section
    suffix ("(a)", ".3", "-1") collapses to the parent group so sub-notes of ONE note share a key. Returns
    [] for a blank tag. The keys are OPAQUE — lower-cased verbatim, never interpreted."""
    if not str(tag or "").strip():
        return []
    out, seen = [], set()
    for part in re.split(r"[,;&]| and ", str(tag)):
        p = part.strip().lower()
        if not p:
            continue
        p = re.sub(r"\s*\([^)]*\)\s*$", "", p)            # drop a trailing "(a)" / "(b)" sub-section
        p = re.sub(r"[.\-]\d+[a-z()]*$", "", p).strip()   # drop a trailing ".3" / "-1" / ".1(d)" sub-section
        p = re.sub(r"^(?:note|notes|n|#)\s*\.?\s*", "", p).strip()   # drop a leading "Note "/"N." → bare key,
        p = re.sub(r"\s+", " ", p)                        # so "Note 15, 30" and "Note 30" both yield key "30"
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def source_routing_audit(tb_rows: list, resolved: dict) -> dict:
    """Cross-check the preparer's Source grouping against the engine's concept-resolution.

    `tb_rows`: dicts carrying `account` + (optional) `source_tag`. `resolved`: {account -> concept_id|None}
    (the engine's OWN routing). Returns:
      {"groups":   {tag_key -> [accounts]},                 # the preparer's proposed grouping (opaque)
       "conflicts":[{tag, accounts, concepts}],             # one tag's rows resolve to >1 concept — surfaced
       "split":    [{concept, tags, accounts}],             # one concept's rows carry >1 tag — surfaced
       "has_source": bool}                                  # False → Source absent → pure no-op
    The build NEVER consumes `groups` to place a row (resolution + the seed concept→note do that); this is a
    confirmable proposal + a flag, never an auto-route."""
    groups: dict = {}
    tags_by_concept: dict = {}
    has_source = False
    for r in tb_rows:
        keys = parse_source_tag(r.get("source_tag", ""))
        if keys:
            has_source = True
        for k in keys:
            groups.setdefault(k, []).append(r["account"])
        cid = resolved.get(r["account"])
        if cid is not None:
            tags_by_concept.setdefault(cid, set()).update(keys)
    conflicts = []
    for k, accts in groups.items():
        concepts = sorted({resolved.get(a) for a in accts if resolved.get(a) is not None})
        if len(concepts) > 1:                              # one tag, several concepts → a routing conflict
            conflicts.append({"tag": k, "accounts": sorted(accts), "concepts": concepts})
    split = [{"concept": c, "tags": sorted(t), "accounts": sorted(a for a in groups_accounts(groups, t))}
             for c, t in tags_by_concept.items() if len(t) > 1]
    return {"groups": groups, "conflicts": conflicts, "split": split, "has_source": has_source}


def groups_accounts(groups: dict, tags) -> list:
    out = []
    for t in tags:
        out += groups.get(t, [])
    return out
