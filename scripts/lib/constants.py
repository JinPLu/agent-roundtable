"""Shared constants for agent-roundtable scripts."""

# Pricing keys that were deprecated after the 2025-Q3 registry refactor.
# Consumers must NOT read these keys from models.json or models.example.json.
DEPRECATED_PRICING_KEYS: frozenset[str] = frozenset({
    "_official_before_discount",
    "_pretax_reference",
})
