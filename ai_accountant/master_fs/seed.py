"""Load a validated master-structure JSON into a per-master `MasterStructureStore`.

A seed is trusted only after GATE 0 (`validate.py`) proves it faithfully represents its approved xlsx,
and its `engine` block is validated at load (`validate_engine_meta`) — a dangling coverage_total /
balance_check / memo_leaf id, or a section that drifts from the concepts, BLOCKS the load (never silently
skipped). STRUCTURE ONLY — no amounts. The engine reads ALL archetype facts from the seed's `engine`
block, so a new seed needs zero engine-code changes.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

from ai_accountant.master_fs.model import (HUMAN_APPROVED_TEMPLATE, MasterConcept, MasterStructureStore)
from ai_accountant.master_fs.validate import validate_engine_meta

_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_SEED = _ROOT / "seeds" / "master_fs_structure_seed.json"
_DEFAULT_REGISTRY = _ROOT / "seeds" / "registry.json"


def load_registry(registry_path=None) -> dict:
    """{id -> {id,label,seed_path,rollups_path}} from the seed registry (id-keyed for lookup)."""
    path = Path(registry_path or _DEFAULT_REGISTRY)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    reg = {e["id"]: e for e in data.get("masters", [])}
    _warn_id_collisions(reg)
    return reg


# DOCUMENTED FALLBACK ONLY — the source of truth is the registry's `detect_thresholds` block. These
# numbers were CALIBRATED on N=2 seeds and are PROVISIONAL; a new seed must be able to re-tune them in the
# registry WITHOUT an engine-code edit (so the verdict path in detect.py never hardcodes them). See
# documentation.md for the re-calibration path and the conservatism (more-unsure-is-safe) bias.
_DEFAULT_DETECT_THRESHOLDS = {"floor": 0.15, "margin": 0.10, "high_bar": 0.30}


def load_detect_thresholds(registry_path=None) -> dict:
    """Archetype-detection thresholds from the registry (`detect_thresholds`), or the documented fallback."""
    path = Path(registry_path or _DEFAULT_REGISTRY)
    if path.exists():
        block = json.loads(path.read_text(encoding="utf-8")).get("detect_thresholds")
        if block:
            return {k: float(block.get(k, _DEFAULT_DETECT_THRESHOLDS[k])) for k in _DEFAULT_DETECT_THRESHOLDS}
    return dict(_DEFAULT_DETECT_THRESHOLDS)


def load_all_masters(registry_path=None) -> dict:
    """{seed_id -> MasterStructureStore} for EVERY registered seed, held at once (for archetype detection)."""
    return {mid: load_master_store(seed_id=mid, registry_path=registry_path)
            for mid in load_registry(registry_path)}


def _warn_id_collisions(reg: dict) -> None:
    """WARN (never fail) if two registry seeds declare the same concept_id — guards the Slice-B detector.
    A real second seed should namespace its ids (e.g. tc_*); an overlap is a smell, surfaced not blocked."""
    seen: dict = {}
    for mid, entry in reg.items():
        p = _ROOT / entry["seed_path"]
        if not p.exists():
            continue
        ids = {c["concept_id"] for rows in json.loads(p.read_text(encoding="utf-8"))["statements"].values()
               for c in rows}
        for cid in ids:
            if cid in seen and seen[cid] != mid:
                warnings.warn(f"concept_id {cid!r} declared by BOTH masters {seen[cid]!r} and {mid!r} "
                              f"— namespace seed ids per archetype", stacklevel=2)
            seen.setdefault(cid, mid)


def _resolve(seed_id, json_path, registry_path) -> "tuple[Path, str]":
    if seed_id is not None:
        reg = load_registry(registry_path)
        if seed_id not in reg:
            raise KeyError(f"seed_id {seed_id!r} not in registry {registry_path or _DEFAULT_REGISTRY}")
        return _ROOT / reg[seed_id]["seed_path"], seed_id
    if json_path is not None:
        return Path(json_path), ""
    return _DEFAULT_SEED, ""


def load_master_store(json_path=None, *, seed_id=None, registry_path=None) -> MasterStructureStore:
    # back-compat: a positional arg is a direct json_path (tests); seed_id resolves via the registry.
    path, resolved_id = _resolve(seed_id, json_path, registry_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = dict(data.get("engine", {}))

    problems = validate_engine_meta(data)                  # FAIL-LOUD at load — never silently skip
    if problems:
        raise ValueError(f"seed {path.name} engine block invalid:\n  - " + "\n  - ".join(problems))

    prov = data.get("provenance_seed", HUMAN_APPROVED_TEMPLATE)
    master_id = meta.get("master_id") or resolved_id or ""
    store = MasterStructureStore(meta=meta, master_id=master_id)
    for statement, rows in data["statements"].items():
        for r in rows:
            store.add(MasterConcept(
                concept_id=r["concept_id"], statement=r["statement"], l0_section=r["l0_section"],
                l1_group=r.get("l1_group"), canonical_concept=r["canonical_concept"],
                label_aliases=dict(r.get("label_aliases", {})), presence=r["presence"],
                order=int(r["order"]), provenance=prov,
                kind=r.get("kind", "leaf"), caveat=r.get("caveat", ""),
                caveat_kind=r.get("caveat_kind", ""),
                components=tuple(tuple(c) for c in r.get("components", []))))
    return store
