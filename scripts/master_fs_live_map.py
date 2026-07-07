"""Run-live-once: map the representative bank TB into the master concepts via LIVE gpt-5.1-2025-11-13,
review the proposals, confirm-and-store them, and write the stored result for the export to replay.

Claude generates the TB (illustrative round numbers — NOT AlJazira's real figures); the MAPPING is the
live GPT-5.1 proposer's job (labels-only). Two-step in one run: propose (live) → apply a confirmation
policy (confirm the confident, mark one as AI-assumed, leave unsure unmapped) → store → write JSON.

    python scripts/master_fs_live_map.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                        # noqa: BLE001
    pass

from ai_accountant.master_fs import (ClientMappingStore, ProvenanceStore, apply_mapping_decisions,
                                     load_master_store, propose_account_concepts)

TS = "2026-06-11T00:00:00Z"
CLIENT = "aljazira_representative"

# Representative AlJazira TB — ILLUSTRATIVE round numbers (NOT the bank's real published figures).
# (account, label, current, prior)  ·  prior=None => the line exists in ONE period only.
REP_TB = [
    ("1010", "Cash & balances with SAMA", 8_500_000, 7_200_000),
    ("1020", "Due from banks and OFIs, net", 3_000_000, 2_800_000),
    ("1030", "Investment securities, net", 22_000_000, 20_000_000),
    ("1040", "Loans and advances to customers, net", 65_000_000, 60_000_000),
    ("1050", "Property and equipment, net", 1_800_000, 1_700_000),
    ("1060", "Goodwill and other intangibles, net", 600_000, None),          # one period only
    ("2010", "Due to banks and OFIs", 4_000_000, 3_500_000),
    ("2020", "Customers' deposits", 80_000_000, 74_000_000),
    ("2030", "Sukuk and term debt issued", 5_000_000, 5_000_000),
    ("2040", "Other liabilities", 1_200_000, 1_100_000),
    ("2050", "Sundry suspense — clearing account", 300_000, 250_000),        # deliberately unmappable
    ("3010", "Share capital", 10_000_000, 10_000_000),
    ("3020", "Statutory reserve", 4_000_000, 3_500_000),
    ("3030", "Retained earnings", 7_300_000, 6_800_000),
    ("3040", "Additional Tier 1 sukuk", 3_000_000, 3_000_000),
    ("4010", "Special commission income", 4_200_000, 3_900_000),
    ("4020", "Special commission expense", -1_500_000, -1_300_000),
    ("4030", "Net fee and commission income", 900_000, 820_000),
    ("4040", "Salaries and general operating expenses", -1_800_000, -1_700_000),
    ("4050", "Impairment charge for expected credit losses", -400_000, -350_000),
    ("5010", "Net change in fair value — FVOCI debt instruments", 120_000, -80_000),
]
# Human review of the live proposals: ACCEPT one medium-confidence mapping as an AI-ASSUMPTION
# (unverified) to exercise that rendering; DECLINE the suspense/clearing account (a human won't confirm
# a clearing balance into a face line — flag-don't-force → it stays unmapped → findings). Everything
# else confident is CONFIRMED.
ASSUME = {"4040"}      # "Salaries and general operating expenses" → Other G&A (medium) — accepted unverified
OPEN = {"2050"}        # "Sundry suspense — clearing account" — reviewer declines, leaves unmapped


def main():
    store = load_master_store()
    items = [(a, lbl) for a, lbl, _c, _p in REP_TB]
    print(f"=== LIVE map: {len(items)} TB lines → master concepts via gpt-5.1-2025-11-13 (labels only) ===")
    proposals = propose_account_concepts(items, store)        # LIVE call

    label_by = {a: lbl for a, lbl, _c, _p in REP_TB}
    decisions, rows = {}, []
    for p in proposals:
        unsure = (p.line.strip().lower() == "unsure") or not p.is_confident
        if unsure or p.code in OPEN:
            decision = "open"
        elif p.code in ASSUME:
            decision = "assume"
        else:
            decision = "confirm"
        decisions[p.code] = decision
        rows.append((p.code, label_by[p.code], p.line, p.confidence, decision, p.evidence))
    for code, label, concept, conf, decision, evidence in rows:
        tag = {"confirm": "→ confirm", "assume": "→ AI-ASSUME", "open": "→ UNSURE/unmapped"}[decision]
        print(f"  {code} {label[:42]:<42} ⇒ {concept[:40]:<40} [{conf:<6}] {tag}")
        if evidence:
            print(f"       evidence: {evidence[:90]}")

    ms, au = ClientMappingStore(), ProvenanceStore()
    apply_mapping_decisions(proposals, store, client_id=CLIENT, decisions=decisions,
                            mapping_store=ms, audit=au, approver="reviewer", at=TS)

    # write the STORED confirmed result (mappings + the TB + audit) for the export to REPLAY
    out = {
        "client": CLIENT, "model": "gpt-5.1-2025-11-13",
        "tb": [{"account": a, "label": lbl, "current": c, "prior": p} for a, lbl, c, p in REP_TB],
        "mappings": [{"account": r.account, "concept_id": r.concept_id, "client_label": r.client_label,
                      "provenance": r.provenance, "confidence": r.confidence,
                      "flagged_reason": r.flagged_reason} for r in ms.mapping(CLIENT).values()],
        "audit": [{"action": a.action, "target": a.target, "provenance": a.provenance,
                   "confidence": a.confidence, "at": a.at, "detail": a.detail} for a in au.records],
    }
    dst = ROOT / "exports" / "master_fs_live.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    mapped = sum(1 for m in out["mappings"] if m["concept_id"])
    print(f"\nstored: {mapped}/{len(out['mappings'])} mapped "
          f"({sum(1 for m in out['mappings'] if m['provenance']=='ai_assumed')} AI-assumed, "
          f"{sum(1 for m in out['mappings'] if not m['concept_id'])} unmapped) → {dst}")


if __name__ == "__main__":
    main()
