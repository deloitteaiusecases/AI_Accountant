"""Validate the sourced policy samples through the policy -> rules -> classify pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.config import get_api_key  # noqa: E402
from ai_accountant.policy import classify, extract_policy_rules  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "policy_samples"


def main() -> None:
    key = get_api_key()
    for path in sorted(SAMPLES.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        out = extract_policy_rules(key, text)
        rules = out.get("mapping_rules", [])
        print(f"\n=== {path.name} ({len(text):,} chars) -> {len(rules)} rules ===")
        for r in rules[:10]:
            print(f"  {str(r.get('asset_type'))[:44]:46} -> {r.get('classification')}")

        # Show policy overriding the IFRS 9 default for a sukuk held to maturity.
        d = classify("Saudi Govt Sukuk 2028 held to maturity", rules)
        print(f"  classify('Saudi Govt Sukuk ... held to maturity') -> "
              f"{d.classification}  [{d.source}]")


if __name__ == "__main__":
    main()
