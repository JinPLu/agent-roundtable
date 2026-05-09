#!/usr/bin/env python3
"""Project-wide turn usage log + recalibration helpers.

Log shape
---------
JSONL at `$ROUNDTABLE_PROJECT_ROOT/.roundtable/usage.log`. One line per
completed turn (success OR failure). Schema documented in
`docs/research/COST_ESTIMATION-2026-05-10.md` §6.4 — fields:

    ts                ISO-8601 UTC
    thread            slug
    actor             "codex" | "claude" | "cursor-subagent"
    model             cli_arg or alias the dispatch used
    role              planner|executor|reviewer|...
    effort            low|medium|high|xhigh
    prompt_tokens     int | None
    completion_tokens int | None
    reasoning_tokens  int (0 if provider didn't expose it)
    cost_estimated_usd float | None  (point estimate from estimate_cost)
    cost_actual_usd    float | None  (None when actor is opaque, e.g. Cursor pool)
    elapsed_s          int
    exit_code          int

A failed turn (no usage data) is still appended with `prompt_tokens: null`
and `exit_code != 0` rather than silently dropped — calibration must see
the failure rate.

Concurrency: append-only. Each writer opens the file with `O_APPEND`, which
the kernel guarantees atomic up to PIPE_BUF (4096 bytes on Linux); JSON
records are well under that. We additionally serialize within a single
process via `_LOCK` so unit tests with multi-thread workers don't tear.

Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import statistics
import threading
from typing import Any, Iterable

DEFAULT_LOG_REL = pathlib.Path(".roundtable") / "usage.log"

_LOCK = threading.Lock()


def _resolve_log_path(log_path: pathlib.Path | str | None) -> pathlib.Path:
    if log_path is not None:
        return pathlib.Path(log_path)
    proj = os.environ.get("ROUNDTABLE_PROJECT_ROOT") or os.environ.get(
        "ROUNDTABLE_REPO_ROOT"
    )
    if not proj:
        raise RuntimeError(
            "ROUNDTABLE_PROJECT_ROOT not set; pass log_path= explicitly or "
            "export the env var (mirrors scripts/_common.sh)."
        )
    return pathlib.Path(proj) / DEFAULT_LOG_REL


# Required + optional fields. The wrapper hooks fill best-effort; missing
# numeric fields are stored as null (json.dumps emits null for None) so the
# JSONL stays parseable.
_REQUIRED = ("ts", "thread", "actor", "model", "role", "exit_code")
_NUMERIC_DEFAULTS: dict[str, Any] = {
    "effort": None,
    "prompt_tokens": None,
    "completion_tokens": None,
    "reasoning_tokens": 0,
    "cost_estimated_usd": None,
    "cost_actual_usd": None,
    "elapsed_s": 0,
}


def _normalize(record: dict) -> dict:
    """Fill defaults + ensure JSON-serializable. Mutates a copy, not input."""
    out: dict[str, Any] = {}
    if "ts" not in record:
        out["ts"] = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    for k in _REQUIRED:
        if k in record:
            out[k] = record[k]
    for k, default in _NUMERIC_DEFAULTS.items():
        out[k] = record.get(k, default)
    for k, v in record.items():
        if k not in out:
            out[k] = v
    return out


def append_usage_record(
    record: dict,
    log_path: pathlib.Path | str | None = None,
) -> pathlib.Path:
    """Append `record` as a single JSONL line. Returns the resolved path.

    Never raises on validation problems — the wrapper hook MUST not change
    the turn's exit status. Instead, malformed records become stub lines
    with a `_log_error` field so calibration can spot them.
    """
    path = _resolve_log_path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    norm = _normalize(record)
    try:
        line = json.dumps(norm, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        # Fall back to a minimal record we can definitely serialize.
        line = json.dumps(
            {
                "ts": norm.get("ts"),
                "thread": str(norm.get("thread") or ""),
                "actor": str(norm.get("actor") or ""),
                "model": str(norm.get("model") or ""),
                "role": str(norm.get("role") or ""),
                "exit_code": int(norm.get("exit_code") or 1),
                "_log_error": f"json encode failed: {exc!r}",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    line_bytes = (line + "\n").encode("utf-8")
    with _LOCK:
        # O_APPEND ensures the kernel does the offset-then-write atomically;
        # multiple processes can append to the same file without locking.
        fd = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
        )
        try:
            os.write(fd, line_bytes)
        finally:
            os.close(fd)
    return path


def read_usage_log(
    log_path: pathlib.Path | str | None = None,
    since_days: int | None = None,
) -> list[dict]:
    """Parse the JSONL log, dropping malformed lines (with stderr would be
    overkill for tooling — recalibrate prints stats including drop count).

    `since_days` filters by the `ts` field (UTC ISO-8601). Records with
    unparseable timestamps pass the filter (better calibration noise than
    silent loss).
    """
    path = _resolve_log_path(log_path)
    if not path.exists():
        return []

    records: list[dict] = []
    cutoff: datetime.datetime | None = None
    if since_days is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=since_days
        )

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if cutoff is not None:
                ts_raw = rec.get("ts")
                if isinstance(ts_raw, str):
                    try:
                        ts = datetime.datetime.strptime(
                            ts_raw, "%Y-%m-%dT%H:%M:%SZ"
                        ).replace(tzinfo=datetime.timezone.utc)
                    except ValueError:
                        ts = None
                    if ts is not None and ts < cutoff:
                        continue
            records.append(rec)
    return records


# ── Recalibration ──────────────────────────────────────────────────────────


def _bucket_key(role: str, thinking: bool) -> str:
    """Recalibration cells are keyed by `role × thinking-bucket` so that
    thinking-mode reasoning-token inflation lands in its own bucket and
    doesn't drag chat-mode budgets up.
    """
    return f"{role}::{'thinking' if thinking else 'chat'}"


def _is_thinking_record(rec: dict) -> bool:
    """Heuristic mirror of estimate_cost._is_thinking using log fields.

    The log itself doesn't carry a thinking flag (we kept the schema
    minimal), so we infer from `model` substring + reasoning_tokens > 0.
    """
    model = (rec.get("model") or "").lower()
    if "thinking" in model or model == "gemini-3.1-pro":
        return True
    rt = rec.get("reasoning_tokens") or 0
    try:
        return int(rt) > 0
    except (TypeError, ValueError):
        return False


def _p50(values: Iterable[int]) -> int | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return int(round(statistics.median(vals)))


def recalibrate_role_budgets(
    records: list[dict],
    current_budgets: dict[str, dict[str, int]],
    *,
    min_samples: int = 5,
) -> dict:
    """Suggest a new ROLE_TOKEN_BUDGETS dict from the log.

    Output dict has the same shape as `estimate_cost.ROLE_TOKEN_BUDGETS`:

        { role: { "input": <int>, "output_chat": <int>, "output_thinking": <int> } }

    Cells with fewer than `min_samples` observations are filled from
    `current_budgets[role]` so we never silently regress to a noisy median.
    Rich metadata is returned alongside via the second tuple element.
    """
    by_bucket: dict[str, dict[str, list[int]]] = {}
    for rec in records:
        role = rec.get("role")
        if not role or role not in current_budgets:
            continue
        if (rec.get("exit_code") or 0) != 0:
            # A failed turn has unreliable usage; skip from p50 but counted
            # in `samples_total` so the recalibration tool can show drop rate.
            continue
        thinking = _is_thinking_record(rec)
        key = _bucket_key(role, thinking)
        bucket = by_bucket.setdefault(key, {"input": [], "output": []})
        pt = rec.get("prompt_tokens")
        ct = rec.get("completion_tokens")
        if isinstance(pt, int) and pt > 0:
            bucket["input"].append(pt)
        if isinstance(ct, int) and ct > 0:
            bucket["output"].append(ct)

    suggested: dict[str, dict[str, int]] = {}
    metadata: dict[str, dict] = {}
    for role, current in current_budgets.items():
        chat_key = _bucket_key(role, False)
        think_key = _bucket_key(role, True)
        chat_bucket = by_bucket.get(chat_key, {"input": [], "output": []})
        think_bucket = by_bucket.get(think_key, {"input": [], "output": []})

        input_values = chat_bucket["input"] + think_bucket["input"]
        n_input = len(input_values)
        n_chat_out = len(chat_bucket["output"])
        n_think_out = len(think_bucket["output"])

        new = dict(current)
        if n_input >= min_samples:
            new["input"] = _p50(input_values) or current["input"]
        if n_chat_out >= min_samples:
            new["output_chat"] = _p50(chat_bucket["output"]) or current["output_chat"]
        if n_think_out >= min_samples:
            new["output_thinking"] = _p50(think_bucket["output"]) or current[
                "output_thinking"
            ]

        suggested[role] = new
        metadata[role] = {
            "n_input": n_input,
            "n_chat_out": n_chat_out,
            "n_think_out": n_think_out,
            "min_samples": min_samples,
            "input_kept_current": n_input < min_samples,
            "chat_kept_current": n_chat_out < min_samples,
            "thinking_kept_current": n_think_out < min_samples,
            "input_p50_observed": _p50(input_values),
            "output_chat_p50_observed": _p50(chat_bucket["output"]),
            "output_thinking_p50_observed": _p50(think_bucket["output"]),
        }
    return {"budgets": suggested, "metadata": metadata}
