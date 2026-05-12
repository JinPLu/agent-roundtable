#!/usr/bin/env python3
"""Loader for the vendored LiteLLM pricing snapshot.

The snapshot lives at `scripts/lib/pricing_snapshot.json`; refresh via
`python3 scripts/refresh_pricing_snapshot.py` (manual, never automatic).

Pricing convention
------------------
The snapshot stores LiteLLM-native PER-TOKEN values
(`input_cost_per_token`, `output_cost_per_token`,
`cache_creation_input_token_cost`, `cache_read_input_token_cost`). This loader
exposes them as PER-1M for symmetry with `models.json`'s `per_1m_input` /
`per_1m_output` rates that `estimate_cost.py` already speaks. The conversion
(×1e6) happens in `get_model_pricing` only — internal callers that want raw
rates can inspect `load_snapshot()['_models'][id]` directly.

Lookup
------
We accept both a "canonical id" (LiteLLM id like `claude-opus-4-7`) and a
project alias resolved via `models.json`'s `cli_arg`. In practice
`estimate_cost.py` already has the registry entry, so it passes the `cli_arg`
straight through; the canonical id matches in the common case.

Stdlib only.
"""
from __future__ import annotations

import json
import pathlib
from typing import Optional

_HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_SNAPSHOT_PATH = _HERE / "pricing_snapshot.json"


class SnapshotError(RuntimeError):
    """Raised when the snapshot is missing or structurally invalid."""


def load_snapshot(path: pathlib.Path | str | None = None) -> dict:
    """Return the parsed snapshot dict.

    Raises SnapshotError if the file is missing or corrupt — callers MUST
    handle this and decide whether to skip-with-warning or fail-hard.
    """
    p = pathlib.Path(path) if path else DEFAULT_SNAPSHOT_PATH
    if not p.exists():
        raise SnapshotError(
            f"pricing snapshot not found at {p}. "
            f"Run scripts/refresh_pricing_snapshot.py to generate it."
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"snapshot at {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "_models" not in data:
        raise SnapshotError(
            f"snapshot at {p} is missing required '_models' key"
        )
    return data


# Process-local cache so multi-call scripts don't re-read the JSON. The
# snapshot is small (a few KB), but estimate_cost is invoked once per
# candidate by route.py and we don't want N file reads for N candidates.
_CACHE: dict[str, dict] = {}


def _cached_snapshot(path: pathlib.Path | str | None) -> dict:
    key = str(pathlib.Path(path).resolve()) if path else str(DEFAULT_SNAPSHOT_PATH)
    if key not in _CACHE:
        _CACHE[key] = load_snapshot(path)
    return _CACHE[key]


def reset_cache() -> None:
    """Drop the in-process snapshot cache (test helper)."""
    _CACHE.clear()


def get_model_pricing(
    canonical_id: str,
    *,
    snapshot_path: pathlib.Path | str | None = None,
) -> Optional[dict]:
    """Return per-1M pricing dict for `canonical_id`, or None.

    Returns None when:
      - the id is missing from the snapshot, OR
      - the entry is marked `_no_litellm_source: true`
        (caller must fall back to models.json).

    Output schema mirrors `models.json` `pricing` blocks for plug-in
    compatibility:
      {
        "per_1m_input":         <float>,
        "per_1m_output":        <float>,
        "per_1m_cache_creation": <float | None>,   # only if upstream had it
        "per_1m_cached_input":  <float | None>,    # only if upstream had it
        "max_input_tokens":     <int | None>,
        "max_output_tokens":    <int | None>,
        "litellm_provider":     <str | None>,
        "_litellm_id":          <str>,
        "_source":              "litellm-snapshot",
      }
    """
    snap = _cached_snapshot(snapshot_path)
    entry = snap.get("_models", {}).get(canonical_id)
    if entry is None or entry.get("_no_litellm_source"):
        return None
    in_pt = entry.get("input_cost_per_token")
    out_pt = entry.get("output_cost_per_token")
    if in_pt is None or out_pt is None:
        return None
    cache_creation_pt = entry.get("cache_creation_input_token_cost")
    cached_pt = entry.get("cache_read_input_token_cost")
    return {
        "per_1m_input": float(in_pt) * 1_000_000.0,
        "per_1m_output": float(out_pt) * 1_000_000.0,
        "per_1m_cache_creation": (
            float(cache_creation_pt) * 1_000_000.0
            if cache_creation_pt is not None
            else None
        ),
        "per_1m_cached_input": (
            float(cached_pt) * 1_000_000.0 if cached_pt is not None else None
        ),
        "max_input_tokens": entry.get("max_input_tokens"),
        "max_output_tokens": entry.get("max_output_tokens"),
        "litellm_provider": entry.get("litellm_provider"),
        "_litellm_id": entry.get("_litellm_id", canonical_id),
        "_source": "litellm-snapshot",
    }


def supports_reasoning(
    canonical_id: str,
    *,
    snapshot_path: pathlib.Path | str | None = None,
) -> bool:
    """LiteLLM-derived flag for thinking/reasoning-token support.

    Returns False (not None) when the id is missing or has no flag — the
    caller can still rely on `_is_thinking()` in estimate_cost which already
    handles cli_arg-based detection (`*-thinking-*`, `gemini-3.1-pro`, …).
    """
    try:
        snap = _cached_snapshot(snapshot_path)
    except SnapshotError:
        return False
    entry = snap.get("_models", {}).get(canonical_id) or {}
    return bool(entry.get("supports_reasoning", False))


def has_entry(
    canonical_id: str,
    *,
    snapshot_path: pathlib.Path | str | None = None,
) -> bool:
    """True if `canonical_id` is whitelisted (even with _no_litellm_source)."""
    try:
        snap = _cached_snapshot(snapshot_path)
    except SnapshotError:
        return False
    return canonical_id in snap.get("_models", {})


def list_known_ids(
    *,
    snapshot_path: pathlib.Path | str | None = None,
    include_stubs: bool = False,
) -> list[str]:
    """All canonical ids in the snapshot, optionally including no-source stubs."""
    try:
        snap = _cached_snapshot(snapshot_path)
    except SnapshotError:
        return []
    out: list[str] = []
    for k, v in (snap.get("_models") or {}).items():
        if not include_stubs and isinstance(v, dict) and v.get("_no_litellm_source"):
            continue
        out.append(k)
    return sorted(out)
