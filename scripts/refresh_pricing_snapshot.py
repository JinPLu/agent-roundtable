#!/usr/bin/env python3
"""Refresh `scripts/lib/pricing_snapshot.json` from LiteLLM upstream.

This is a **manual, auditable** operation — never run at install time and
never at runtime. The vendored snapshot is committed to the repo; refresh
follows the workflow in `docs/research/COST_ESTIMATION-2026-05-10.md` §6.1.

Workflow:
  1. Fetch LiteLLM's `model_prices_and_context_window.json` (MIT licence).
  2. Filter to the WHITELIST (top-of-file constant). Models NOT on the
     whitelist are silently dropped — by design, the snapshot is small.
  3. For models on the whitelist that LiteLLM does not have, emit a
     `_no_litellm_source: true` marker. We DO NOT fabricate prices —
     Cursor pool models in particular live in `models.json` only.
  4. Diff the new payload vs the existing snapshot, print a one-line
     summary (`+ X new, ~ Y changed (cost delta), - Z removed`), and
     remind the user to commit the result.

Network usage:
  - Uses `urllib.request` from stdlib only (no `requests`).
  - Honors `http_proxy` / `https_proxy` if set.
  - Offline fallback: if the fetch fails AND the existing snapshot has a
    valid header, we keep the existing snapshot and exit nonzero with a
    clear message. The estimator still works against the cached snapshot.

Why not auto-fetch on dispatch:
  - The pricing surface should be reviewable in PRs (a $0.001 -> $0.01
    typo in our heuristic is expensive). The vendored snapshot makes
    every price change a visible diff.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request

# ── Whitelist ──────────────────────────────────────────────────────────────
# Canonical LiteLLM model ids that map to actors we route through. We deliberately
# include short and dated forms (e.g. `gpt-5.5` AND `gpt-5.5-2026-04-23`) so
# the registry can resolve either alias. Cursor pool models are NOT in LiteLLM
# (verified 2026-05-10); they stay in `models.json`/`models.example.json`.
LITELLM_WHITELIST: list[str] = [
    # OpenAI direct (matches `cli_arg` in models.json BYOK entries)
    "gpt-5.5",
    "gpt-5.5-2026-04-23",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5-codex",
    "gpt-5.3-codex",
    # Anthropic direct (`cli_arg: claude-opus-4-7`, `claude-sonnet-4-6`, etc.)
    "claude-opus-4-7",
    "claude-opus-4-7-20260416",
    "claude-opus-4-6",
    "claude-opus-4-6-20260205",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    # Google Gemini (cursor-gemini-3.1-pro underlying; via Vertex/Gemini SDK)
    "gemini-3.1-pro-preview",
]

# Models we route through but LiteLLM does not list. We MUST emit a
# `_no_litellm_source: true` stub for them so consumers know to fall back to
# `models.json` rather than failing silently. Order doesn't matter; values are
# free-form notes.
NO_LITELLM_SOURCE: dict[str, str] = {
    # Cursor's pool entries — Cursor does not publish a LiteLLM key.
    # `cli_arg`s (or `cursor_model_slug`s) for our cursor-* aliases.
    "composer-2-fast": "Cursor Composer 2 — Cursor pool, no LiteLLM key. Pricing in models.json.",
    "claude-opus-4-7-thinking-high": "cursor-claude-4.7-opus thinking variant — Cursor doesn't publish a LiteLLM id.",
    "claude-4.6-opus-high-thinking": "cursor-claude-4.6-opus thinking variant — Cursor doesn't publish a LiteLLM id.",
    "claude-4.6-sonnet-medium-thinking": "cursor-claude-4.6-sonnet thinking variant — Cursor doesn't publish a LiteLLM id.",
    "gemini-3.1-pro": "cursor-gemini-3.1-pro short id — LiteLLM uses `gemini-3.1-pro-preview`.",
    "gpt-5.5-medium": "cursor-gpt-5.5 effort variant — Cursor doesn't publish a LiteLLM id.",
    "gpt-5.4-medium": "cursor-gpt-5.4 effort variant — Cursor doesn't publish a LiteLLM id.",
    # DeepSeek BYOK aliases used by claude-* claude_turn entries.
    "deepseek-v4-pro": "DeepSeek v4-pro — not in LiteLLM as of 2026-05-10.",
    "deepseek-v4-pro[1m]": "DeepSeek v4-pro long-context flag — not in LiteLLM.",
    "deepseek-v4-flash": "DeepSeek v4-flash — not in LiteLLM as of 2026-05-10.",
}

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
SNAPSHOT_PATH = pathlib.Path(__file__).resolve().parent / "lib" / "pricing_snapshot.json"

# Fields we mirror from LiteLLM. Keep the set tight: only what `estimate_cost`
# can actually use. We DO NOT mirror provider-specific quirks (e.g. region
# routing, batch flags) to keep the snapshot reviewable.
_KEEP_FIELDS = (
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_read_input_token_cost",
    "cache_creation_input_token_cost",
    "max_input_tokens",
    "max_output_tokens",
    "supports_reasoning",
    "supports_prompt_caching",
    "supports_tool_choice",
    "litellm_provider",
    "mode",
)


def _fetch_litellm(timeout_s: int = 30) -> tuple[dict, str | None]:
    """Return (parsed_json, etag_or_none). Raises URLError on network failure."""
    req = urllib.request.Request(
        LITELLM_URL, headers={"User-Agent": "agent-roundtable/refresh-pricing-snapshot"}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
        etag = resp.headers.get("ETag")
    parsed = json.loads(body.decode("utf-8"))
    return parsed, etag


def _filter_whitelist(upstream: dict) -> dict[str, dict]:
    """Slice LiteLLM's giant dict down to whitelist + slim per-model fields."""
    out: dict[str, dict] = {}
    for canonical_id in LITELLM_WHITELIST:
        entry = upstream.get(canonical_id)
        if entry is None:
            out[canonical_id] = {
                "_no_litellm_source": True,
                "_note": (
                    f"Whitelisted id {canonical_id!r} not present in LiteLLM upstream "
                    "as of fetch; estimator must fall back to models.json."
                ),
            }
            continue
        slim: dict = {"_litellm_id": canonical_id}
        for k in _KEEP_FIELDS:
            if k in entry:
                slim[k] = entry[k]
        out[canonical_id] = slim
    for stub_id, note in NO_LITELLM_SOURCE.items():
        out.setdefault(stub_id, {"_no_litellm_source": True, "_note": note})
    return out


def _diff(old_models: dict, new_models: dict) -> dict:
    """Compute a small diff summary for the user-visible refresh report."""
    added = sorted(set(new_models) - set(old_models))
    removed = sorted(set(old_models) - set(new_models))
    changed: list[tuple[str, str]] = []
    for k in sorted(set(old_models) & set(new_models)):
        before = old_models[k]
        after = new_models[k]
        if before == after:
            continue
        bi = before.get("input_cost_per_token")
        ai = after.get("input_cost_per_token")
        bo = before.get("output_cost_per_token")
        ao = after.get("output_cost_per_token")
        bits = []
        if bi != ai:
            bits.append(f"in {bi}->{ai}")
        if bo != ao:
            bits.append(f"out {bo}->{ao}")
        if not bits:
            bits.append("metadata only")
        changed.append((k, ", ".join(bits)))
    return {"added": added, "removed": removed, "changed": changed}


def _build_payload(models: dict, *, etag: str | None, fetched_iso: str) -> dict:
    return {
        "_source": LITELLM_URL,
        "_fetched": fetched_iso,
        "_litellm_commit_or_etag": etag or "unknown",
        "_whitelist_size": len(LITELLM_WHITELIST),
        "_no_litellm_source_count": len(NO_LITELLM_SOURCE),
        "_schema": (
            "Pricing values are PER-TOKEN (LiteLLM native). Helpers in "
            "scripts/lib/pricing_snapshot.py convert to per-1M for downstream "
            "consumers. _no_litellm_source=true rows have no pricing — caller "
            "must fall back to models.json. See COST_ESTIMATION-2026-05-10.md §6.1."
        ),
        "_models": models,
    }


def _hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default=str(SNAPSHOT_PATH),
        help=f"snapshot path to write (default: {SNAPSHOT_PATH})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds for the LiteLLM fetch (default 30).",
    )
    parser.add_argument(
        "--allow-offline-stub",
        action="store_true",
        help=(
            "If LiteLLM fetch fails AND no snapshot exists yet, write a "
            "_no_litellm_source-only stub so tests/imports still run. Never "
            "use this in CI; intended for fully air-gapped first-run only."
        ),
    )
    args = parser.parse_args(argv)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fetched_iso = datetime.date.today().isoformat()

    upstream: dict | None = None
    etag: str | None = None
    try:
        upstream, etag = _fetch_litellm(timeout_s=args.timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        if out_path.exists():
            print(
                f"ERROR: LiteLLM fetch failed ({exc}); existing snapshot at "
                f"{out_path} kept untouched. Re-run with network access to refresh.",
                file=sys.stderr,
            )
            return 2
        if not args.allow_offline_stub:
            print(
                f"ERROR: LiteLLM fetch failed ({exc}) and no snapshot exists. "
                "Re-run with network access, or pass --allow-offline-stub for "
                "a no-pricing stub.",
                file=sys.stderr,
            )
            return 2
        print(
            f"WARN: LiteLLM fetch failed ({exc}); writing offline stub with "
            "_no_litellm_source markers only. Refresh as soon as network is up.",
            file=sys.stderr,
        )
        upstream = {}
        etag = None

    new_models = _filter_whitelist(upstream)
    new_payload = _build_payload(new_models, etag=etag, fetched_iso=fetched_iso)

    old_models: dict = {}
    if out_path.exists():
        try:
            old_payload = json.loads(out_path.read_text(encoding="utf-8"))
            old_models = old_payload.get("_models", {})
        except (json.JSONDecodeError, OSError):
            old_models = {}

    diff = _diff(old_models, new_models)
    out_path.write_text(json.dumps(new_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"snapshot: {out_path}")
    print(
        f"+ {len(diff['added'])} new, ~ {len(diff['changed'])} changed (cost delta), "
        f"- {len(diff['removed'])} removed"
    )
    for name in diff["added"][:10]:
        print(f"  + {name}")
    for name, why in diff["changed"][:10]:
        print(f"  ~ {name}: {why}")
    for name in diff["removed"][:10]:
        print(f"  - {name}")
    print(
        f"sha16={_hash(new_payload)} fetched={fetched_iso} "
        f"litellm_etag={etag or 'unknown'}"
    )
    print(
        "Reminder: this is a vendored snapshot. Review the diff, then "
        "`git add scripts/lib/pricing_snapshot.json && git commit`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
