"""Print the value-routing map for the bundled sample."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.collect import collect_from_path  # noqa: E402
from ai_accountant.routing import build_routing_map  # noqa: E402

rm = build_routing_map(collect_from_path(str(SAMPLE_NOTE5_CSV)))
print(f"{'Lvl':4} {'Used':5} {'Role':30} Table")
print("-" * 70)
for e in rm.entries:
    used = "USED" if e.used_in_cascade else ""
    print(f"{e.level or '?':4} {used:5} {e.role:30} {e.table_title or '-'}")
