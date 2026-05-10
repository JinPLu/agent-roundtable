#!/usr/bin/env python3
"""research_cache.py - one-shot pricing-freshness gate per thread.

Wraps check_pricing_freshness.check_freshness() and caches the result so the
parent agent does not repeat the freshness check on every dispatch within the
same thread (Hard Rule #3 efficiency improvement).

Cache invalidation:
  - Cache file is older than CACHE_TTL_HOURS (default 24h), OR
  - models.json SHA-256 has changed since the cache was written.

Usage:
    python3 scripts/lib/research_cache.py --thread <slug> [--project <path>]

Exit codes:
    0  OK — pricing is fresh (or cache confirms it was checked recently)
    1  STALE — pricing is stale and user declined refresh (non-interactive)
    2  ERROR — cannot locate thread dir or models.json

Stdout (first line machine-parseable):
    "CACHE_HIT   checked_at=<iso>"
    "CACHE_MISS  freshness_ok=True  wrote_cache=<path>"
    "CACHE_MISS  freshness_ok=False  (stale pricing)"
    "CACHE_INVALIDATED  reason=<hash_changed|expired>  re-checked=True"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]
_MODELS_JSON = _SKILL_DIR / "models.json"
_CACHE_TTL_HOURS = 24
_CACHE_FILENAME = ".research_cache.json"

# Module-level import so tests can patch `research_cache.check_freshness`.
try:
    from check_pricing_freshness import check_freshness  # type: ignore[import]
except ImportError:  # pragma: no cover — only missing in very stripped environments
    check_freshness = None  # type: ignore[assignment]


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR [research_cache]: {msg}", file=sys.stderr)
    sys.exit(code)


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hours_since(iso: str) -> float:
    then = datetime.fromisoformat(iso)
    now = datetime.now(timezone.utc)
    # Make sure both are tz-aware
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 3600


def _read_cache(cache_path: pathlib.Path) -> dict | None:
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(cache_path: pathlib.Path, snapshot_hash: str) -> None:
    cache_path.write_text(
        json.dumps({"checked_at": _now_iso(), "snapshot_hash": snapshot_hash}, indent=2),
        encoding="utf-8",
    )


def ensure_research_baseline(thread_dir: pathlib.Path, models_json: pathlib.Path | None = None) -> int:
    """Check / refresh pricing freshness; return 0 on OK, 1 on stale, 2 on error."""
    if models_json is None:
        models_json = _MODELS_JSON

    if not models_json.exists():
        # No registry yet; setup hasn't run — skip silently.
        print("CACHE_SKIP  models.json not found; skipping freshness check")
        return 0

    cache_path = thread_dir / _CACHE_FILENAME
    current_hash = _sha256_file(models_json)
    cached = _read_cache(cache_path)

    if cached:
        age_h = _hours_since(cached.get("checked_at", "1970-01-01T00:00:00+00:00"))
        cached_hash = cached.get("snapshot_hash", "")

        if cached_hash == current_hash and age_h < _CACHE_TTL_HOURS:
            print(f"CACHE_HIT   checked_at={cached['checked_at']}")
            return 0

        reason = "hash_changed" if cached_hash != current_hash else "expired"
        print(f"CACHE_INVALIDATED  reason={reason}  re-checking...")

    # Run actual freshness check
    try:
        if check_freshness is None:
            raise ImportError("check_pricing_freshness not available")
        fresh = check_freshness(registry_path=models_json, interactive=False)
    except Exception as exc:
        print(f"CACHE_ERROR  could not run check_freshness: {exc}", file=sys.stderr)
        return 2

    if fresh:
        thread_dir.mkdir(parents=True, exist_ok=True)
        _write_cache(cache_path, current_hash)
        print(f"CACHE_MISS  freshness_ok=True  wrote_cache={cache_path}")
        return 0
    else:
        print("CACHE_MISS  freshness_ok=False  (stale pricing — run scripts/refresh_pricing_snapshot.py)")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--thread", required=True, help="Thread slug")
    parser.add_argument("--project", default=None,
                        help="Project root (defaults to $ROUNDTABLE_PROJECT_ROOT or git toplevel)")
    args = parser.parse_args(argv)

    project_root_str = args.project or os.environ.get("ROUNDTABLE_PROJECT_ROOT")
    if not project_root_str:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode == 0:
            project_root_str = r.stdout.strip()
        else:
            _die("Cannot determine project root; set ROUNDTABLE_PROJECT_ROOT or run inside a git repo.")

    project_root = pathlib.Path(project_root_str)
    thread_dir = project_root / ".roundtable" / "threads" / args.thread

    if not thread_dir.exists():
        _die(f"Thread directory not found: {thread_dir}")

    return ensure_research_baseline(thread_dir)


if __name__ == "__main__":
    sys.exit(main())
