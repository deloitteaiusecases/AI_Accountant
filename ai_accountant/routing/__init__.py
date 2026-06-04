"""Routing: classify tables by level and build the value-routing map."""
from ai_accountant.routing.router import (
    ai_normalize_tables,
    build_routing_map,
    detect_role,
    enrich_routing_map_with_ai,
    map_columns_with_ai,
    triage_files,
)

__all__ = [
    "ai_normalize_tables",
    "build_routing_map",
    "detect_role",
    "enrich_routing_map_with_ai",
    "map_columns_with_ai",
    "triage_files",
]
