"""Build step (re-runnable, idempotent): stamp HUMAN-AUTHORED roll-ups onto a master seed — now driven
by the seed REGISTRY so it operates per archetype, not a single hardcoded pair.

For each registry entry: if its `rollups_path` does NOT exist, SKIP-WITH-NOTICE (a seed with no authored
rollups is NOT a fidelity pass — "no rollups yet" != "fidelity OK"). Otherwise stamp each computed
concept's `kind`/`components` from the authored file, add any `must_add_to_seed` totals that are missing
(idempotent), and regenerate the flat `.csv` if the seed has one. The seed's `engine` block is preserved.

    python scripts/apply_rollups_to_seed.py            # --all (every registry entry)
    python scripts/apply_rollups_to_seed.py --seed-id ksa_bank
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ai_accountant.master_fs import load_registry, validate_rollups   # noqa: E402


def _stamp_one(seed_path: Path, rollups_path: Path) -> str:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    authored = json.loads(rollups_path.read_text(encoding="utf-8"))
    rollups = authored["rollups"]

    for rows in seed["statements"].values():
        for r in rows:
            spec = rollups.get(r["concept_id"])
            r["kind"] = spec["kind"] if spec else "leaf"
            r["components"] = [list(c) for c in spec["components"]] if spec else []

    present = {c["concept_id"] for rows in seed["statements"].values() for c in rows}
    added = 0
    for cid in authored.get("must_add_to_seed", []):
        if cid in present:
            continue                                    # idempotent — already added on a prior run
        spec = rollups[cid]
        after = {"bs_total_assets": "bs_other_assets", "bs_total_liabilities": "bs_other_liab",
                 "bs_total_equity": "bs_tier1", "bs_total_liab_equity": "bs_total_equity"}.get(cid)
        concept = {"concept_id": cid, "statement": spec["statement"], "l0_section": spec["l0_section"],
                   "l1_group": None, "canonical_concept": spec["canonical"], "label_aliases": {},
                   "presence": "both", "order": int(spec["order"]), "kind": spec["kind"],
                   "components": [list(c) for c in spec["components"]]}
        bs = seed["statements"]["balance_sheet"]
        idx = next((i for i, r in enumerate(bs) if r["concept_id"] == after), len(bs) - 1)
        bs.insert(idx + 1, concept)
        added += 1

    seed_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = seed_path.with_suffix(".csv")
    if csv_path.exists():
        cols = ["statement", "l0_section", "l1_group", "concept_id", "canonical_concept",
                "aljazira_label", "saab_label", "presence", "order"]
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(cols)
            for rows in seed["statements"].values():
                for r in rows:
                    a = r.get("label_aliases", {})
                    w.writerow([r["statement"], r["l0_section"], r.get("l1_group") or "", r["concept_id"],
                                r["canonical_concept"], a.get("aljazira", ""), a.get("saab", ""),
                                r["presence"], r["order"]])
    fid = validate_rollups(str(seed_path), str(rollups_path))
    return f"stamped ({added} total(s) added) · fidelity {'PASS' if not fid else fid}"


def main() -> None:
    reg = load_registry()
    target = None
    if "--seed-id" in sys.argv:
        target = sys.argv[sys.argv.index("--seed-id") + 1]
    for mid, entry in reg.items():
        if target and mid != target:
            continue
        rp = ROOT / entry["rollups_path"]
        if not rp.exists():
            print(f"[{mid}] SKIP-WITH-NOTICE — no authored rollups at {entry['rollups_path']} "
                  f"(its roll-ups are inline in the seed; NOT a fidelity pass)")
            continue
        print(f"[{mid}] " + _stamp_one(ROOT / entry["seed_path"], rp))


if __name__ == "__main__":
    main()
