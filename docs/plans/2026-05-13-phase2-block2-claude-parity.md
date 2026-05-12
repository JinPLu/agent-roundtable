# Phase 2 块② Claude CLI 深集成对齐 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (this repo's preferred path, inline batch). Steps use checkbox (`- [ ]`) syntax for tracking. Spec: `docs/specs/2026-05-13-phase2-block2-claude-parity-design.md`.

**Goal:** Two PRs delivering (a) model-aware faithful USD accounting for Claude turns, (b) explicit `--resume <session_id>` replacing coarse `--continue`, and (e) Haiku `Explore` subagent injection for read-heavy roles. Success measured by proxy-side billing A/B: PR1 cuts Claude bill ≥ 50%, PR2 cuts an additional ≥ 10% on top.

**Architecture:** PR1 (修车) repairs `extract_claude_usage.py` to use `pricing_snapshot.json`'s 4-tier per-token rates (input / cache_creation / cache_read / output) and swaps the single line in `claude_turn.sh` that adds `--continue` for `--resume <sid>` (sid is already captured in a marker file by the existing infrastructure — only the use changed). PR2 (新装) edits 6 role system-prompt files to instruct the model to call `Task(subagent_type="Explore", thoroughness="medium")` as the first action of read-heavy turns.

**Tech Stack:** Python 3.10+ stdlib (no new deps); bash with existing `_resume.sh` helpers; Claude Code CLI ≥ 2.1.x (`--resume` and Task subagent are documented in [CLI reference](https://code.claude.com/docs/en/cli-reference)); existing LiteLLM-derived `pricing_snapshot.json` exposing `cache_creation_input_token_cost` / `cache_read_input_token_cost` / `input_cost_per_token` / `output_cost_per_token`.

---

## PR 1: 修车（a + b）

### Task 1: Expose cache_creation rate from `get_model_pricing`

**Why:** `pricing_snapshot.py:get_model_pricing()` today returns `per_1m_input`, `per_1m_output`, and `per_1m_cached_input` (the cache_read price). It does NOT expose `cache_creation_input_token_cost`, which is what `extract_claude_usage` (Task 2) needs for correct attribution. We extend the return dict additively — no caller changes break.

**Files:**
- Modify: `scripts/lib/pricing_snapshot.py` (extend `get_model_pricing`)
- Test: `scripts/lib/test_pricing_snapshot.py` (create — repo currently has no test for this module)

- [ ] **Step 1: Write failing test**

Create `scripts/lib/test_pricing_snapshot.py`:

```python
"""Tests for pricing_snapshot.get_model_pricing cache_creation field."""
from __future__ import annotations

import pathlib

import pricing_snapshot as ps


def test_get_model_pricing_exposes_cache_creation(tmp_path: pathlib.Path) -> None:
    """Opus 4.7 entry has cache_creation_input_token_cost 6.25e-6 → 6.25/1M."""
    ps.reset_cache()
    out = ps.get_model_pricing("claude-opus-4-7-20260416")
    assert out is not None, "claude-opus-4-7-20260416 must exist in snapshot"
    assert out["per_1m_input"] == 5.0
    assert out["per_1m_output"] == 25.0
    assert out["per_1m_cached_input"] == 0.5
    assert out["per_1m_cache_creation"] == 6.25


def test_get_model_pricing_cache_creation_none_when_missing(tmp_path: pathlib.Path) -> None:
    """A model without cache_creation_input_token_cost yields None for that field."""
    snap = tmp_path / "snap.json"
    snap.write_text(
        '{"_models": {"foo": {"_litellm_id": "foo", '
        '"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6, '
        '"cache_read_input_token_cost": 5e-7}}}'
    )
    ps.reset_cache()
    out = ps.get_model_pricing("foo", snapshot_path=snap)
    assert out is not None
    assert out["per_1m_cache_creation"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /media/datasets/OminiEWM_Data/tmp/ljp/agent-roundtable
PYTHONPATH=scripts/lib pytest scripts/lib/test_pricing_snapshot.py -v
```

Expected: 2 failures, both with `KeyError: 'per_1m_cache_creation'` on the assertion line.

- [ ] **Step 3: Implement**

In `scripts/lib/pricing_snapshot.py`, modify `get_model_pricing` (around line 113–125) to add `per_1m_cache_creation`:

```python
    cached_pt = entry.get("cache_read_input_token_cost")
    cache_creation_pt = entry.get("cache_creation_input_token_cost")
    return {
        "per_1m_input": float(in_pt) * 1_000_000.0,
        "per_1m_output": float(out_pt) * 1_000_000.0,
        "per_1m_cached_input": (
            float(cached_pt) * 1_000_000.0 if cached_pt is not None else None
        ),
        "per_1m_cache_creation": (
            float(cache_creation_pt) * 1_000_000.0
            if cache_creation_pt is not None
            else None
        ),
        "max_input_tokens": entry.get("max_input_tokens"),
        "max_output_tokens": entry.get("max_output_tokens"),
        "litellm_provider": entry.get("litellm_provider"),
        "_litellm_id": entry.get("_litellm_id", canonical_id),
        "_source": "litellm-snapshot",
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=scripts/lib pytest scripts/lib/test_pricing_snapshot.py -v
```

Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/pricing_snapshot.py scripts/lib/test_pricing_snapshot.py
git commit -m "feat(pricing): expose cache_creation rate in get_model_pricing

Add per_1m_cache_creation alongside per_1m_cached_input. Additive change,
no existing callers broken. Required by extract_claude_usage rewrite to
attribute cache-creation tokens at 1.25x input price (Anthropic billing
schema)."
```

---

### Task 2: Rewrite `extract_claude_usage.py` to model-aware 4-tier pricing

**Why:** Current implementation uses hardcoded sonnet ballpark (`$3/$0.30/$15`) regardless of actual model, and lumps `cache_creation_input_tokens` (1.25× input price per Anthropic) and `cache_read_input_tokens` (0.1× input price) into one bucket. After this task, `real_usd` in `usage.json` matches Anthropic's actual billing math for Opus 4.7, Sonnet 4.5, and any model with a snapshot entry.

**Files:**
- Modify: `scripts/lib/extract_claude_usage.py` (full rewrite of `compute()`)
- Modify: `scripts/lib/test_extract_claude_usage.py` (extend existing tests + new cases)

- [ ] **Step 1: Write failing tests**

Replace contents of `scripts/lib/test_extract_claude_usage.py` with:

```python
"""Tests for extract_claude_usage 4-tier model-aware pricing."""
from __future__ import annotations

import json
import pathlib

import extract_claude_usage as ec
import pricing_snapshot as ps


def _write_last(tmp_path: pathlib.Path, model: str, usage: dict) -> pathlib.Path:
    p = tmp_path / "last.json"
    p.write_text(json.dumps({"model": model, "usage": usage}))
    return p


def test_opus_47_four_tier_pricing(tmp_path: pathlib.Path) -> None:
    """All 4 token categories priced from snapshot at correct multipliers."""
    ps.reset_cache()
    last = _write_last(
        tmp_path,
        "claude-opus-4-7-20260416",
        {
            "input_tokens": 2000,
            "cache_creation_input_tokens": 8000,
            "cache_read_input_tokens": 50000,
            "output_tokens": 1000,
        },
    )
    out = ec.compute(last)
    assert out["usage_found"] is True
    assert out["model"] == "claude-opus-4-7-20260416"
    # Snapshot for opus-4-7-20260416: input 5/1M, output 25/1M,
    # cache_read 0.5/1M, cache_creation 6.25/1M.
    expected = (
        2000 / 1_000_000 * 5.0
        + 8000 / 1_000_000 * 6.25
        + 50000 / 1_000_000 * 0.5
        + 1000 / 1_000_000 * 25.0
    )
    assert abs(out["real_usd"] - expected) < 1e-6
    assert out["cached_input_ratio"] == 50000 / (2000 + 8000 + 50000)


def test_unknown_model_falls_back_to_sonnet_ballpark(tmp_path: pathlib.Path) -> None:
    """If snapshot has no entry, fall back to coarse sonnet rates (current behaviour)."""
    ps.reset_cache()
    last = _write_last(
        tmp_path,
        "claude-not-real-2099",
        {
            "input_tokens": 1000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 100,
        },
    )
    out = ec.compute(last)
    assert out["usage_found"] is True
    assert out["pricing_source"] == "fallback-sonnet-ballpark"
    expected = 1000 / 1_000_000 * 3.0 + 100 / 1_000_000 * 15.0
    assert abs(out["real_usd"] - expected) < 1e-6


def test_no_usage_field(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "last.json"
    p.write_text(json.dumps({"model": "claude-opus-4-7-20260416"}))
    out = ec.compute(p)
    assert out["usage_found"] is False


def test_missing_file() -> None:
    out = ec.compute(pathlib.Path("/no/such/path/last.json"))
    assert out["usage_found"] is False


def test_cli_write_path(tmp_path: pathlib.Path) -> None:
    last = _write_last(
        tmp_path,
        "claude-opus-4-7-20260416",
        {"input_tokens": 100, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 0, "output_tokens": 10},
    )
    out_file = tmp_path / "usage.json"
    rc = ec.main([str(last), "--write", str(out_file)])
    assert rc == 0
    data = json.loads(out_file.read_text())
    assert data["usage_found"] is True
    assert "real_usd" in data and "model" in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=scripts/lib pytest scripts/lib/test_extract_claude_usage.py -v
```

Expected: All 5 tests fail (current `compute()` lacks `model` field handling and 4-tier logic).

- [ ] **Step 3: Implement**

Replace `scripts/lib/extract_claude_usage.py` body with:

```python
#!/usr/bin/env python3
"""Faithful Anthropic billing accounting from Claude Code last.json usage.

Reads `last.json` written by `claude -p --output-format stream-json`. Looks
up per-token prices from `pricing_snapshot.json` (LiteLLM-derived) keyed by
the model field. Anthropic's billing schema:

    bill = input_tokens × P_input
         + cache_creation_input_tokens × P_input × 1.25
         + cache_read_input_tokens × P_input × 0.10
         + output_tokens × P_output

The snapshot already stores P_cache_creation and P_cache_read explicitly,
so we use those directly rather than multipliers.

When the model is not in the snapshot, falls back to the historical sonnet
ballpark rates ($3 / $15 / $0.30 cached) and tags `pricing_source` so the
ledger can flag those rows.

Stream-json usage duplication bug (anthropics/claude-code#6805): we read
from last.json's terminal `result` event, not the partial stream. The
verification script `test_claude_last_json_usage_one_time.py` (Task 3)
confirms last.json is not affected.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional

try:
    import pricing_snapshot as ps
except ImportError:  # pragma: no cover — script also runnable as a direct file
    _HERE = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(_HERE))
    import pricing_snapshot as ps

# Fallback (only used when the model is missing from the snapshot).
_FALLBACK_INPUT = 3.0
_FALLBACK_CACHE_READ = 0.30
_FALLBACK_CACHE_CREATE = 3.75  # input × 1.25
_FALLBACK_OUTPUT = 15.0


def _usage_from_last(data: dict) -> dict:
    u = data.get("usage")
    if isinstance(u, dict):
        return u
    r = data.get("result")
    if isinstance(r, dict):
        u2 = r.get("usage")
        if isinstance(u2, dict):
            return u2
    return {}


def _model_from_last(data: dict) -> str:
    return str(data.get("model") or "")


def _pricing_for_model(model: str) -> tuple[dict, str]:
    """Return (rates_per_1m_dict, source_tag)."""
    if model:
        try:
            entry = ps.get_model_pricing(model)
        except ps.SnapshotError:
            entry = None
        if entry is not None:
            input_1m = entry["per_1m_input"]
            output_1m = entry["per_1m_output"]
            cache_read_1m = entry.get("per_1m_cached_input")
            cache_create_1m = entry.get("per_1m_cache_creation")
            return (
                {
                    "input": input_1m,
                    "output": output_1m,
                    "cache_read": (
                        cache_read_1m
                        if cache_read_1m is not None
                        else input_1m * 0.10
                    ),
                    "cache_create": (
                        cache_create_1m
                        if cache_create_1m is not None
                        else input_1m * 1.25
                    ),
                },
                "litellm-snapshot",
            )
    return (
        {
            "input": _FALLBACK_INPUT,
            "output": _FALLBACK_OUTPUT,
            "cache_read": _FALLBACK_CACHE_READ,
            "cache_create": _FALLBACK_CACHE_CREATE,
        },
        "fallback-sonnet-ballpark",
    )


def compute(last_path: pathlib.Path) -> dict:
    if not last_path.exists():
        return {"usage_found": False}
    try:
        data = json.loads(last_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {"usage_found": False}
    raw = _usage_from_last(data)
    if not raw:
        return {"usage_found": False}

    inp = int(raw.get("input_tokens") or 0)
    cc = int(raw.get("cache_creation_input_tokens") or 0)
    cr = int(raw.get("cache_read_input_tokens") or 0)
    out = int(raw.get("output_tokens") or 0)

    model = _model_from_last(data)
    rates, source = _pricing_for_model(model)

    real_usd = (
        inp / 1_000_000 * rates["input"]
        + cc / 1_000_000 * rates["cache_create"]
        + cr / 1_000_000 * rates["cache_read"]
        + out / 1_000_000 * rates["output"]
    )

    total_input = inp + cc + cr
    cached_ratio = (cr / total_input) if total_input > 0 else 0.0

    return {
        "usage_found": True,
        "model": model,
        "pricing_source": source,
        "input_tokens": inp,
        "cache_creation_input_tokens": cc,
        "cache_read_input_tokens": cr,
        "output_tokens": out,
        "cached_input_ratio": round(cached_ratio, 6),
        "real_usd": round(real_usd, 8),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("last_json", type=pathlib.Path)
    ap.add_argument("--write", type=pathlib.Path, default=None)
    args = ap.parse_args(argv)
    payload = compute(args.last_json)
    print(json.dumps(payload))
    if args.write:
        args.write.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if payload.get("usage_found") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=scripts/lib pytest scripts/lib/test_extract_claude_usage.py scripts/lib/test_pricing_snapshot.py -v
```

Expected: 7 passes total.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/extract_claude_usage.py scripts/lib/test_extract_claude_usage.py
git commit -m "feat(usage): model-aware 4-tier Claude usage accounting

extract_claude_usage now reads last.json.model, looks up per-token rates
in pricing_snapshot.json, and prices input / cache_creation / cache_read /
output separately. Anthropic's 1.25x cache_create and 0.1x cache_read
multipliers are honored. Adds cached_input_ratio and pricing_source fields
to usage.json. Falls back to sonnet ballpark for unknown models with an
explicit pricing_source='fallback-sonnet-ballpark' tag so the ledger can
flag affected rows."
```

---

### Task 3: One-time verify `last.json` usage is not affected by stream-json duplication bug

**Why:** [anthropics/claude-code#6805](https://github.com/anthropics/claude-code/issues/6805) reports `--output-format stream-json` duplicates token usage across `thinking` / `text` / `tool_use` events. Our `extract_claude_usage` reads the terminal `last.json` (a single `result` event), so should be safe — but verify and document.

**Files:**
- Create: `scripts/lib/verify_claude_usage_not_double_counted.py` (one-shot helper, kept in repo as evidence)

- [ ] **Step 1: Write the verification script**

```python
#!/usr/bin/env python3
"""One-shot check: does last.json from `--output-format stream-json` carry
duplicated usage relative to a sibling `--output-format json` run on the
same prompt?

Run this manually once before relying on extract_claude_usage. Compares
usage between two short throwaway Claude turns. Documents outcome in this
file's docstring (commit the result).

Usage:
    python3 scripts/lib/verify_claude_usage_not_double_counted.py
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


PROMPT = (
    "Echo the literal string EXAMPLE_PROBE and nothing else. No tool calls."
)


def _run(format_flag: str, work: pathlib.Path) -> dict:
    out = work / f"out_{format_flag}.json"
    cmd = [
        "claude",
        "-p",
        "--output-format",
        format_flag,
        "--max-turns",
        "1",
        "--bare",
        PROMPT,
    ]
    if format_flag == "stream-json":
        cmd += ["--verbose"]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(work),
    )
    out.write_text(res.stdout)
    return {"rc": res.returncode, "stderr": res.stderr[-2000:], "path": str(out)}


def _last_event(path: pathlib.Path) -> dict | None:
    try:
        for raw in reversed(path.read_text().splitlines()):
            line = raw.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return None


def main() -> int:
    if not shutil.which("claude"):
        print("claude CLI not on PATH; abort", file=sys.stderr)
        return 2
    work = pathlib.Path(tempfile.mkdtemp(prefix="claude-usage-verify-"))
    print(f"workdir={work}")
    j = _run("json", work)
    s = _run("stream-json", work)
    j_evt = _last_event(pathlib.Path(j["path"]))
    s_evt = _last_event(pathlib.Path(s["path"]))
    j_usage = (j_evt or {}).get("usage") or (j_evt or {}).get("result", {}).get("usage")
    s_usage = (s_evt or {}).get("usage") or (s_evt or {}).get("result", {}).get("usage")
    print("== --output-format json terminal usage:")
    print(json.dumps(j_usage, indent=2))
    print("== --output-format stream-json terminal usage:")
    print(json.dumps(s_usage, indent=2))
    if j_usage and s_usage:
        ratio = (
            (s_usage.get("input_tokens") or 0)
            / max(j_usage.get("input_tokens") or 1, 1)
        )
        print(f"stream/json input_tokens ratio = {ratio:.3f}")
        if ratio > 1.5:
            print("WARN: stream-json appears to inflate usage; extract should use --output-format json")
            return 1
        print("OK: stream-json terminal event matches json output within ±50% — extraction safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the verification**

```bash
cd /media/datasets/OminiEWM_Data/tmp/ljp/agent-roundtable
python3 scripts/lib/verify_claude_usage_not_double_counted.py
```

Expected: prints `OK: stream-json terminal event matches json output within ±50% — extraction safe`. Cost: 2 trivial Claude turns ≈ $0.01.

If the verification fails, STOP and report — `extract_claude_usage` must be re-pointed at the `--output-format json` path. (This is the §6.1 排查 #4 fallback in the spec.)

- [ ] **Step 3: Document the outcome in `extract_claude_usage.py` docstring**

Edit the top docstring of `extract_claude_usage.py` to replace the line:

```
The verification script `test_claude_last_json_usage_one_time.py` (Task 3)
confirms last.json is not affected.
```

with one of:

- **If verification passed:**

  ```
  Verified 2026-05-13 via verify_claude_usage_not_double_counted.py that
  stream-json terminal `result` event carries the same usage as
  `--output-format json` (no duplication bug in last.json).
  ```

- **If verification failed:** also modify `claude_turn.sh:164` to remove `stream-json` from the dispatch args and switch to `--output-format json`; open a separate issue for the partial-stream loss in idle_watchdog.

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/verify_claude_usage_not_double_counted.py scripts/lib/extract_claude_usage.py
git commit -m "test(usage): one-shot verify last.json not affected by stream-json bug

anthropic/claude-code#6805 reports duplicate usage across stream-json
events. Our extract reads the terminal result event from last.json; this
verifier compares stream-json terminal usage against --output-format json
on the same probe prompt to confirm no inflation. Documented outcome in
extract_claude_usage.py header."
```

---

### Task 4: Swap `--continue` for `--resume <session_id>` in `claude_turn.sh`

**Why:** The marker file `<thread>/.claude_session.<role>.<model>.json` already contains `session_id`. `claude_turn.sh:177` already reads it into `_claude_resume_sid` (but currently only for log output). Line 176 adds `--continue` (coarse, picks "most recent session in cwd" → unsafe under concurrent threads). One-line swap: when sid is present, use `--resume "$_claude_resume_sid"`; when sid is empty (legacy markers), fall through to fresh.

**Files:**
- Modify: `scripts/claude_turn.sh:170-179`
- Modify: `scripts/lib/test_resume_policy.py` (extend existing tests)

- [ ] **Step 1: Write failing tests**

Append to `scripts/lib/test_resume_policy.py` (if file doesn't exist, create it):

```python
"""Tests for claude_turn.sh resume-flag construction.

We can't run claude live; instead simulate the relevant sub-shell by
calling a helper that takes a marker and prints the would-be CLI flags.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import textwrap


HELPER = textwrap.dedent('''
    #!/usr/bin/env bash
    set -euo pipefail
    SKILL_DIR="${1}"
    marker="${2}"
    model="${3}"
    role="${4}"
    blind="${5:-0}"
    source "${SKILL_DIR}/scripts/lib/_resume.sh"

    flags=()
    if _should_resume "$role" "$marker" "$blind" "$model"; then
        sid="$(jq -r '.session_id // empty' "$marker" 2>/dev/null || true)"
        if [[ -n "$sid" ]]; then
            flags+=( --resume "$sid" )
        fi
    fi
    printf '%s\\n' "${flags[@]:-}"
''')


def _run_helper(tmp_path: pathlib.Path, marker_data: dict | None,
                 model: str, role: str, blind: str = "0") -> list[str]:
    skill_dir = pathlib.Path(__file__).resolve().parents[2]
    marker = tmp_path / "marker.json"
    if marker_data is not None:
        marker.write_text(json.dumps(marker_data))
    helper = tmp_path / "h.sh"
    helper.write_text(HELPER)
    helper.chmod(0o755)
    res = subprocess.run(
        [str(helper), str(skill_dir), str(marker), model, role, blind],
        capture_output=True, text=True, check=False,
        env={**os.environ, "ROUNDTABLE_PROJECT_ROOT": "/nonexistent"},
    )
    return [s for s in res.stdout.splitlines() if s]


def test_planner_with_valid_marker_emits_resume_sid(tmp_path: pathlib.Path) -> None:
    import time
    marker = {
        "session_id": "abc-123-uuid",
        "ts": int(time.time()),
        "model": "claude-opus-4-7-20260416",
        "git_sha": "",
    }
    flags = _run_helper(
        tmp_path, marker, "claude-opus-4-7-20260416", "planner",
    )
    # planner default is fresh; refine mode would resume — but here we
    # test the executor-class path. Use executor role.
    flags = _run_helper(
        tmp_path, marker, "claude-opus-4-7-20260416", "executor",
    )
    assert flags == ["--resume", "abc-123-uuid"]


def test_reviewer_never_resumes(tmp_path: pathlib.Path) -> None:
    import time
    marker = {
        "session_id": "x", "ts": int(time.time()),
        "model": "claude-opus-4-7-20260416", "git_sha": "",
    }
    flags = _run_helper(
        tmp_path, marker, "claude-opus-4-7-20260416", "reviewer",
    )
    assert flags == []


def test_blind_never_resumes(tmp_path: pathlib.Path) -> None:
    import time
    marker = {
        "session_id": "x", "ts": int(time.time()),
        "model": "claude-opus-4-7-20260416", "git_sha": "",
    }
    flags = _run_helper(
        tmp_path, marker, "claude-opus-4-7-20260416", "executor", blind="1",
    )
    assert flags == []


def test_marker_without_session_id_falls_through(tmp_path: pathlib.Path) -> None:
    """Legacy marker shape without session_id ⇒ no --resume, no --continue."""
    import time
    marker = {
        "ts": int(time.time()),
        "model": "claude-opus-4-7-20260416",
        "git_sha": "",
    }
    flags = _run_helper(
        tmp_path, marker, "claude-opus-4-7-20260416", "executor",
    )
    assert flags == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest scripts/lib/test_resume_policy.py -v -k "session_id or never_resumes or falls_through"
```

Expected: the first test fails because production code currently emits `--continue` instead of `--resume <sid>`. The helper above mimics the *target* behaviour, so these tests pin the desired contract.

- [ ] **Step 3: Implement the swap in `claude_turn.sh`**

Replace the block at `scripts/claude_turn.sh:166-179` (the `── CX1: role-aware session resume` section) with:

```bash
# ── b · explicit --resume <session_id> (CL1) ──────────────────────────────────
# Marker existence + policy table decides whether to resume. Marker file
# `<thread>/.claude_session.<role>.<model>.json` is written post-turn (see
# below). Anthropic CLI: `claude --resume <id>` is the documented per-session
# resume flag (cli-reference §--resume). We deliberately do NOT fall back to
# --continue when the marker lacks session_id: --continue picks "most recent
# session for cwd" which is unsafe under concurrent threads.
_session_marker_model="$(printf '%s' "${model:-default}" | tr '/:' '__')"
_claude_session_marker="${thread_dir}/.claude_session.${role}.${_session_marker_model}.json"
_claude_resume=0
_claude_resume_sid=""
if _should_resume "$role" "$_claude_session_marker" "$blind" "${model:-}"; then
  _claude_resume_sid="$(jq -r '.session_id // empty' "$_claude_session_marker" 2>/dev/null || true)"
  if [[ -n "$_claude_resume_sid" ]]; then
    _claude_resume=1
    _args+=( --resume "$_claude_resume_sid" )
    echo "INFO [claude_turn.sh]: resuming claude session (role=${role}, model=${_session_marker_model}, sid=${_claude_resume_sid:0:8}…)" >&2
  else
    echo "INFO [claude_turn.sh]: marker present but no session_id (legacy); starting fresh." >&2
  fi
fi
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest scripts/lib/test_resume_policy.py -v
PYTHONPATH=scripts/lib pytest scripts/lib/ -v
```

Expected: all green.

- [ ] **Step 5: Smoke check claude_turn.sh syntax**

```bash
bash -n scripts/claude_turn.sh
```

Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/claude_turn.sh scripts/lib/test_resume_policy.py
git commit -m "feat(claude): explicit --resume <session_id> replaces --continue

claude_turn.sh now uses claude --resume <sid> (sid pulled from the existing
marker file) instead of the coarse --continue flag. --continue picks 'most
recent session for cwd', which is unsafe when multiple agent-roundtable
threads run concurrently in the same project. Closes one-period note CL1.

No fallback to --continue when sid is missing: legacy markers ⇒ fresh turn."
```

---

### Task 5: PR1 integration smoke + push

- [ ] **Step 1: Run full lib test suite**

```bash
cd /media/datasets/OminiEWM_Data/tmp/ljp/agent-roundtable
PYTHONPATH=scripts/lib pytest scripts/lib/ -v
```

Expected: all green.

- [ ] **Step 2: Run existing hook smoketests**

```bash
bash hooks/_smoketests/run_all.sh 2>&1 | tail -20
```

Expected: 5/5 smoketests pass (jq must be present).

- [ ] **Step 3: Push PR1**

```bash
git push origin main
```

(User decides timing of push — wait for explicit user OK before pushing.)

- [ ] **Step 4: User runs A/B benchmark gate (manual)**

User invokes the standard "small feature" task with Claude Opus 4.7 actor twice:
- **Before pulling PR1 (baseline)**: from `git checkout <commit-before-PR1>`
- **After pulling PR1**: from `git checkout <PR1 HEAD>`

The "small feature" task is:

> Goal: add a `--summary` flag to `scripts/lib/check_budget.py` so that
> `python3 scripts/lib/check_budget.py <thread_dir> --summary` prints
> total real_usd of last 10 turns, per-role subtotals, and average
> cached_input_ratio.

User compares proxy billing dashboard total Anthropic spend across the two runs.

**Pass criterion:** PR1 spend ≤ 50% of baseline spend. (Most of the gap is the cache_read multiplier correction.)

**Fail criterion:** spend reduction < 50% → run `verify_claude_usage_not_double_counted.py` (Task 3) one more time; check `pricing_snapshot.json` has the actual Opus 4.7 dated slug; revert PR1 if blocker.

---

## PR 2: 新装（e）

### Task 6: Add Explore-first directive to planner / researcher / researcher-deep

**Why:** Planner and researcher roles are read-heavy. By instructing them to call `Task(subagent_type="Explore", thoroughness="medium")` as their first action, they delegate the file-survey phase to Haiku (Anthropic's free read-only subagent, ~10× cheaper than Opus per token). Subsequent narrow reads by the main model run only on Haiku-flagged files. Documentation: [Claude Code Task Tool Deep Dive](https://gist.github.com/johnlindquist/d22c70fd70660b4f6fb4d0b05d0792d2).

**Files:**
- Modify: `roles/planner.system.md`
- Modify: `roles/researcher.system.md`
- Modify: `roles/researcher-deep.system.md`

- [ ] **Step 1: Append directive to `roles/planner.system.md`**

Append this section at the end of the file (after the existing role guidance):

```markdown

## Cost-aware repo discovery (Phase 2 / 2026-05-13)

**Before** you start producing the PLAN.md, your **first action MUST be** a
call to the built-in Claude Code subagent `Explore`:

```python
Task(
  subagent_type="Explore",
  thoroughness="medium",
  prompt="Survey the repository for files relevant to: <restate the goal in
1 sentence>. Return a list of files with one-line summaries. Read-only."
)
```

The `Explore` subagent runs on Claude Haiku — roughly an order of magnitude
cheaper per token than the main model — and is read-only by design. After
Explore returns, you read only the specific files it flagged. Do not
pre-emptively read files Explore did not recommend.

Allowed exception: if the goal is so narrow that you already know all
relevant paths from GOAL.md / THREAD.md, skip Explore and note "Skipping
Explore — paths preset in GOAL.md" in your output's opening paragraph.

This rule is for cost reasons only; it does not change planning quality
expectations.
```

- [ ] **Step 2: Append the same directive to `roles/researcher.system.md`**

(Identical text. Per writing-plans skill: "repeat the code — the engineer may be reading tasks out of order".)

Append at the end of `roles/researcher.system.md`:

```markdown

## Cost-aware repo discovery (Phase 2 / 2026-05-13)

**Before** you start producing your research notes, your **first action
MUST be** a call to the built-in Claude Code subagent `Explore`:

```python
Task(
  subagent_type="Explore",
  thoroughness="medium",
  prompt="Survey the repository for files relevant to: <restate the
research question in 1 sentence>. Return a list of files with one-line
summaries. Read-only."
)
```

The `Explore` subagent runs on Claude Haiku — roughly an order of magnitude
cheaper per token than the main model — and is read-only by design. After
Explore returns, you read only the specific files it flagged. Do not
pre-emptively read files Explore did not recommend.

Allowed exception: if the question is bounded to external citations only
(no repo files in scope), skip Explore.

This rule is for cost reasons only; it does not change research depth
expectations.
```

- [ ] **Step 3: Append the same directive to `roles/researcher-deep.system.md`**

Append at the end of `roles/researcher-deep.system.md`, identical to Step 2 but with the opening phrase changed:

```markdown

## Cost-aware repo discovery (Phase 2 / 2026-05-13)

**Before** you start producing your deep-research output, your **first
action MUST be** a call to the built-in Claude Code subagent `Explore`:

```python
Task(
  subagent_type="Explore",
  thoroughness="very thorough",
  prompt="Survey the repository for files relevant to: <restate the deep
research question in 1 sentence>. Return a list of files with full
summaries. Read-only."
)
```

(Use `thoroughness="very thorough"` here instead of "medium" — deep research
is worth the extra Haiku time.)

The `Explore` subagent runs on Claude Haiku — roughly an order of magnitude
cheaper per token than the main model — and is read-only by design. After
Explore returns, you read only the specific files it flagged. Do not
pre-emptively read files Explore did not recommend.

This rule is for cost reasons only; it does not change deep-research depth
expectations.
```

- [ ] **Step 4: Commit**

```bash
git add roles/planner.system.md roles/researcher.system.md roles/researcher-deep.system.md
git commit -m "feat(roles): Haiku Explore prelude for planner & researcher

Planner and researcher / researcher-deep system prompts now require a
Task(subagent_type='Explore') first-action. Explore runs on Claude Haiku
(~10x cheaper than Opus) and is read-only; the main model then reads only
Explore-flagged files. Skip-clauses guard against unbounded/trivial cases.

Executor / discussant roles deliberately unchanged — write-heavy and
short-turn workloads don't benefit from Explore overhead."
```

---

### Task 7: Add Explore-first directive to reviewer / reviewer-aggregator / devils-advocate

**Why:** Reviewer-class roles are the most read-heavy turns in any thread (they need to understand the full diff + surrounding context). They benefit most from Haiku exploration.

**Files:**
- Modify: `roles/reviewer.system.md`
- Modify: `roles/reviewer-aggregator.system.md`
- Modify: `roles/devils-advocate.system.md`

- [ ] **Step 1: Append directive to `roles/reviewer.system.md`**

Append at the end of `roles/reviewer.system.md`:

```markdown

## Cost-aware diff discovery (Phase 2 / 2026-05-13)

**Before** you read any source file under review, your **first action
MUST be** a call to the built-in Claude Code subagent `Explore`:

```python
Task(
  subagent_type="Explore",
  thoroughness="medium",
  prompt="Identify files touched by the change under review (see
PLAN.md tasks and recent git diff). Return: (1) modified files with
one-line summary of the change, (2) related files in the same module
that are NOT modified but inform the review. Read-only."
)
```

After Explore returns, read only files it flagged. Do not pre-emptively
read files Explore did not recommend. This rule is for cost reasons only;
it does not change review rigor or finding-completeness expectations.

Allowed exception: if the diff is < 50 lines in a single file, skip Explore
and read that file directly. Note this choice in your verdict.json
preamble.
```

- [ ] **Step 2: Append same directive (slightly adapted) to `roles/reviewer-aggregator.system.md`**

Append:

```markdown

## Cost-aware repo discovery (Phase 2 / 2026-05-13)

When aggregating multiple per-reviewer verdicts, your input is mostly the
verdict.json files plus the original diff — minimal repo read. **Skip
Explore by default**, but if you do need to verify a controversial
finding against actual source, use:

```python
Task(
  subagent_type="Explore",
  thoroughness="quick",
  prompt="Find file <path> and adjacent context for verifying finding:
<one-sentence finding summary>. Read-only."
)
```

This rule is for cost reasons only; it does not change aggregation rigor.
```

- [ ] **Step 3: Append same directive to `roles/devils-advocate.system.md`**

Append (use the reviewer text from Step 1, since devils-advocate is functionally a reviewer-class turn).

```markdown

## Cost-aware diff discovery (Phase 2 / 2026-05-13)

**Before** you read any source file in your adversarial scan, your **first
action MUST be** a call to the built-in Claude Code subagent `Explore`:

```python
Task(
  subagent_type="Explore",
  thoroughness="medium",
  prompt="Identify files touched by the change under review plus
risk-adjacent files (security, locking, error paths). Return file list
with one-line risk-summary. Read-only."
)
```

After Explore returns, read only the files it flagged. Do not pre-emptively
read files Explore did not recommend. This rule is for cost reasons only;
it does not relax your adversarial intensity.
```

- [ ] **Step 4: Commit**

```bash
git add roles/reviewer.system.md roles/reviewer-aggregator.system.md roles/devils-advocate.system.md
git commit -m "feat(roles): Haiku Explore prelude for reviewer trio

Reviewer / reviewer-aggregator / devils-advocate now front-load Haiku
exploration before reading source. Aggregator's exception is special-cased
(verdict-merging is rarely repo-read-heavy)."
```

---

### Task 8: PR2 integration smoke + push

- [ ] **Step 1: Sanity-check no other role files reference old non-existent directives**

```bash
grep -RIn "Cost-aware repo discovery" roles/
grep -RIn "Cost-aware diff discovery" roles/
```

Expected: 4 matches under "repo" (planner, researcher, researcher-deep, reviewer-aggregator) + 2 under "diff" (reviewer, devils-advocate). Total 6 files.

- [ ] **Step 2: Confirm executor / executor-fast / executor-heavy / discussant untouched**

```bash
grep -ln "Cost-aware" roles/executor*.system.md roles/discussant.system.md 2>/dev/null
```

Expected: empty output (no matches — these roles intentionally do NOT get the directive).

- [ ] **Step 3: Push PR2**

```bash
git push origin main
```

(Wait for explicit user OK to push.)

- [ ] **Step 4: User runs A/B benchmark gate 2 (manual)**

Run the same "small feature" task as Gate 1 a third time, from `git checkout <PR2 HEAD>`.

User compares proxy billing total of this run vs the PR1-after total from Gate 1.

**Pass criterion:** PR2 spend ≤ 90% of PR1 spend (≥ 10% additional reduction).

**Fail criterion:** spend equal or higher → revert PR2 (preserve PR1).

---

## Self-Review (writing-plans §"Self-Review")

| Check | Result |
|-------|--------|
| Spec coverage: every spec section mapped to a task | ✅ Spec §4.1 → Task 1+2+3; §4.2 → Task 4; §5 → Tasks 6+7; §6 → Tasks 5+8 (A/B gates); §3 → A/B gates in 5+8 |
| Placeholder scan (`TBD`, `TODO`, "implement later", "add handling") | ✅ none. All steps contain executable commands or full code |
| Type / function consistency | ✅ `get_model_pricing` returns same shape across Tasks 1+2; `_should_resume` / `_write_session_marker` names match `_resume.sh` |
| File path accuracy | ✅ all paths verified against repo via Glob/Grep before writing this plan |

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-05-13-phase2-block2-claude-parity.md`.

Two execution options:

1. **Inline Execution (recommended for this plan)** — Execute tasks in this session using `superpowers:executing-plans`, with explicit gate at end of PR1 (Task 5 Step 4 A/B benchmark) before starting PR2. This plan has only 8 tasks and ~6 files, inline is more efficient than subagent dispatch.

2. **Subagent-Driven** — Dispatch a fresh subagent per task. Adds overhead but isolates per-task context. Use if you expect to need parallel work on other Phase 2 blocks simultaneously.

Recommend: **Inline Execution**, pausing for user OK after PR1 (Tasks 1-5) before continuing to PR2 (Tasks 6-8).
