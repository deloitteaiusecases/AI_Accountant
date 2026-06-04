"""DEPRECATED — kept only as a compatibility shim.

The original engine.py functions were migrated into the `ai_accountant` package during the
Phase 0 restructure (2026-06-03). Import from the new locations instead:

    profile_uploaded_csvs   -> ai_accountant.ingestion.profile_uploaded_files
    parse_policy_document   -> ai_accountant.policy.parse_policy_document
    extract_policy_rules    -> ai_accountant.policy.extract_policy_rules
    ai_triage               -> ai_accountant.routing.triage_files

This shim re-exports them so any old references keep working; it will be removed later.
"""
from ai_accountant.ingestion import profile_uploaded_files as profile_uploaded_csvs
from ai_accountant.policy import extract_policy_rules, parse_policy_document
from ai_accountant.routing import triage_files as ai_triage

__all__ = [
    "profile_uploaded_csvs",
    "parse_policy_document",
    "extract_policy_rules",
    "ai_triage",
]
