#!/usr/bin/env python3
"""Check pricing freshness for active models in models.json."""
import json
import pathlib
import sys
from datetime import date

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]


def check_freshness(registry_path=None, *, interactive=True) -> bool:
    """Return True if all pricing is fresh (or pinned), False if stale and user declined."""
    if registry_path is None:
        registry_path = _SKILL_DIR / "models.json"
        if not registry_path.exists():
            return True  # no registry, skip
    reg = json.loads(registry_path.read_text())
    models = reg.get("models", {})
    active = reg.get("active", {})
    today = date.today()
    stale = []
    for actor_key, alias in active.items():
        if not alias:
            continue
        m = models.get(alias, {})
        pricing = m.get("pricing") or {}
        as_of = pricing.get("_as_of")
        pinned = pricing.get("_pinned", False)
        if not as_of or pinned:
            continue
        try:
            age = (today - date.fromisoformat(as_of)).days
        except ValueError:
            continue
        if age > 30:
            stale.append((alias, as_of, age, pricing.get("source", "no source URL")))
    if not stale:
        return True
    for alias, as_of, age, source in stale:
        print(f"\nSTALE PRICING: {alias}._as_of={as_of} ({age} days old).")
        print(f"  Source: {source}")
        print("  Run 'backend.sh discover-models <base_url>' or WebSearch the source URL,")
        print("  then update models.json with current rates. Set _pinned: true to override.")
    if not interactive:
        return False  # non-interactive mode: treat stale as error
    answer = input("\nContinue with stale pricing? [y/N] ").strip().lower()
    return answer in ("y", "yes")


if __name__ == "__main__":
    interactive = "--non-interactive" not in sys.argv
    ok = check_freshness(interactive=interactive)
    sys.exit(0 if ok else 1)
