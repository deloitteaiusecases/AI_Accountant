"""Archetype detection — the DETERMINISTIC verdict (no LLM here, no archetype literals, no threshold
numbers). The model (in `mapping.propose_archetype`) does labels-only per-label semantic fit and returns,
per TB label, which registered chart(s) it is consistent with (+ evidence) and, per chart, a few signature
lines ABSENT from the TB. This module turns that into a grounded SCORE and a CONSERVATIVE verdict:

  score[X] = (# TB labels that fit EXACTLY chart X) / (# TB labels)        — the discriminating-label
             fraction; generic labels (fit >=2 charts) and unmatched labels score nobody.

A single seed is PROPOSED only on a clear win (high top AND clear margin AND a non-strong runner-up);
otherwise the verdict is UNSURE -> BLOCK (below_floor / multi_high / near_tie). "Highest score wins" is
NOT the default — unsure is the easy landing, because a confident WRONG archetype is the worst outcome.
The thresholds are CONFIG (passed in from the registry), never literals here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArchetypeRanking:
    seed_id: str
    label: str                          # registry label (human-readable)
    score: float                        # 0..1 — the deterministic discriminating-label fraction
    matched: list = field(default_factory=list)   # (tb_label, evidence) that fit ONLY this seed (FOR)
    absent: list = field(default_factory=list)     # this seed's signature lines NOT found in the TB


@dataclass
class ArchetypeProposal:
    verdict: str                        # "propose" | "unsure"
    seed_id: "str | None"               # the single proposed seed_id ONLY when verdict == "propose"
    ranked: list = field(default_factory=list)     # [ArchetypeRanking], score-desc, ALL seeds
    block_reason: "str | None" = None   # "below_floor" | "multi_high" | "near_tie" | None
    finding: "str | None" = None        # when unsure: ranked scores + the conflict, for the human


def archetype_verdict(per_label, absent, items, fingerprints, thresholds) -> ArchetypeProposal:
    """per_label: [{"label":.., "fits":[seed_id...], "evidence":..}] (the model's labels-only fit).
    absent: {seed_id: [signature lines missing from the TB]}. fingerprints: {seed_id: {"label":..}}.
    thresholds: {"floor","margin","high_bar"} from the registry. ALL deterministic from here on."""
    seed_ids = list(fingerprints)
    disc = {sid: [] for sid in seed_ids}
    for pl in per_label:
        fits = [s for s in pl.get("fits", []) if s in disc]
        if len(fits) == 1:                              # fits EXACTLY one chart -> discriminating
            disc[fits[0]].append((pl.get("label", ""), pl.get("evidence", "")))
    n = max(len(items), 1)

    ranked = [ArchetypeRanking(seed_id=sid, label=fingerprints[sid].get("label", sid),
                               score=round(len(disc[sid]) / n, 4), matched=disc[sid],
                               absent=list(absent.get(sid, []))) for sid in seed_ids]
    ranked.sort(key=lambda r: r.score, reverse=True)

    floor, margin, high = thresholds["floor"], thresholds["margin"], thresholds["high_bar"]
    s1 = ranked[0].score if ranked else 0.0
    s2 = ranked[1].score if len(ranked) > 1 else 0.0

    if ranked and s1 >= floor and (s1 - s2) >= margin and s2 < high:
        return ArchetypeProposal(verdict="propose", seed_id=ranked[0].seed_id, ranked=ranked)

    # UNSURE -> BLOCK. Most fundamental reason first.
    if s1 < floor:
        reason = "below_floor"          # nothing matches well — likely an archetype we have no seed for
    elif s2 >= high:
        reason = "multi_high"           # two charts both strong — the TB looks like several
    else:
        reason = "near_tie"             # genuine ambiguity between the top two
    finding = (f"Archetype UNSURE ({reason}) — a human must confirm. Ranked: "
               + "; ".join(f"{r.label} {r.score:.2f}" for r in ranked)
               + ". No seed is selected by default.")
    return ArchetypeProposal(verdict="unsure", seed_id=None, ranked=ranked,
                             block_reason=reason, finding=finding)
