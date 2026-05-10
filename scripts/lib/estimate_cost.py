#!/usr/bin/env python3
"""Heuristic per-turn USD cost estimator for agent-roundtable dispatches.

Why this exists
---------------
The chat parent's hand-estimates were ~20x off for Cursor + thinking models
because thinking-mode output (reasoning tokens) inflates 10x+ vs chat-mode
output and is billed as output tokens. Token *rates* in `models.json` /
`models.example.json` are correct per cursor.com/docs/models-and-pricing
(verified 2026-05-10); the failure mode is *token-count* assumption. This
script encodes per-role / per-effort token-count buckets so the dispatch
confirmation block can show a defensible band instead of a guess.

Pricing source resolution (--source flag)
-----------------------------------------
  registry  default — use models.json / models.example.json `pricing` block.
  snapshot  use scripts/lib/pricing_snapshot.json (vendored LiteLLM whitelist).
            For Cursor pool models (cursor-*, no LiteLLM key) we transparently
            fall back to registry — they have no other source of truth.
  both      compute against each, warn (in result.notes) when the rates
            disagree by > 10% so the user knows the registry is stale.

Calibration source & freshness
------------------------------
  See ../../docs/research/AGENT_LOOPS-2026-05-10.md for the empirical
  observations behind the buckets below (agentic input ~50K-200K, thinking
  output ~10K-50K, tool-call blocks billed as output, etc.).

  ROLE_TOKEN_BUDGETS and EFFORT_MULTIPLIERS are HEURISTICS. They should be
  re-calibrated quarterly against actual observed turn sizes (sample
  history/<role>/<ts>/ from the last 30 days, take p50). DO NOT silently
  edit these numbers in passing — leave a NOTE comment with date and the
  observation that justified the change so the contract stays auditable.

Public CLI surface (stdlib only):
  python3 scripts/lib/estimate_cost.py \\
    --model <alias> --role <role> [--turns N]
    [--effort low|medium|high|xhigh]   default medium
    [--max-mode]                       2x input rate when input > 200k
    [--teams]                          add Cursor Token Rate $0.25/M
                                       (Teams plan only; non-Composer/Auto)
    [--json]                           machine-readable output

The script prefers `models.json` (user's gitignored registry) and falls
back to `models.example.json` so it works on a fresh clone, mirroring
`route.py`'s registry resolution.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Pricing-snapshot loader (lazy to keep estimate_cost importable when the
# snapshot is missing — first-run on a fresh clone).
try:
    import pricing_snapshot as _ps  # type: ignore  # noqa: E402
except ImportError:  # pragma: no cover — only triggers if file is gone
    _ps = None  # type: ignore


def _default_registry() -> pathlib.Path:
    """Prefer the gitignored models.json; fall back to models.example.json."""
    real = _SKILL_DIR / "models.json"
    if real.exists():
        return real
    return _SKILL_DIR / "models.example.json"


# === HEURISTIC TABLE — public contract; edit only with a dated NOTE ========
#
# input            = typical input tokens per turn (project context + prompt
#                    + tool-call results that get re-injected)
# output_chat      = typical output tokens for a non-thinking model
# output_thinking  = typical output tokens for a thinking model (reasoning
#                    tokens billed as output)
#
# Buckets reflect agentic CLI turns (Codex / Claude Code / Cursor Task) at
# medium effort, with project context (AGENTS.md + repo browsing). Pure-chat
# turns without project context are 5-10x smaller; do not use this table for
# them. See AGENT_LOOPS-2026-05-10.md §3 for the source data.
ROLE_TOKEN_BUDGETS: dict[str, dict[str, int]] = {
    "planner":             {"input": 50_000,  "output_chat": 4_000,  "output_thinking": 15_000},
    "executor":            {"input": 80_000,  "output_chat": 8_000,  "output_thinking": 25_000},
    # executor-fast: mechanical edits, smaller context window read, smaller emit.
    # Tuned for sweeps/scaffolding — if a turn needs >2k output it's drifting
    # into regular executor budget. NOTE 2026-05-11: derived from gpt-5.5 low
    # history p50=45s × 34 tok/s ~= 1500 tokens emit, rounded up.
    "executor-fast":       {"input": 40_000,  "output_chat": 2_000,  "output_thinking": 5_000},
    # researcher: reads many docs (high input), produces options table (medium
    # output). Reasoning fills the thinking output.
    "researcher":          {"input": 100_000, "output_chat": 6_000,  "output_thinking": 18_000},
    # researcher-deep: same input scale but heavier synthesis; output similar
    # to executor-heavy but with no tool emission.
    "researcher-deep":     {"input": 100_000, "output_chat": 8_000,  "output_thinking": 25_000},
    "reviewer":            {"input": 60_000,  "output_chat": 3_000,  "output_thinking": 12_000},
    "devils-advocate":     {"input": 60_000,  "output_chat": 3_000,  "output_thinking": 12_000},
    "reviewer-aggregator": {"input": 30_000,  "output_chat": 2_000,  "output_thinking": 8_000},
    "discussant":          {"input": 30_000,  "output_chat": 5_000,  "output_thinking": 12_000},
}

# Effort multipliers stack on top of the role bucket. "high" disproportionately
# inflates output because most "more thinking" budget is spent on reasoning
# tokens (which are billed as output), not on new prose.
EFFORT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "low":    {"input": 0.6, "output": 0.5},
    "medium": {"input": 1.0, "output": 1.0},
    "high":   {"input": 1.4, "output": 1.8},
    "xhigh":  {"input": 1.8, "output": 3.0},
}

# Per-turn cost distributions are heavy-tailed (a single deep refactor turn
# can be 10x the median). Wide bands make this honest rather than precise.
LOW_BAND, HIGH_BAND = 0.5, 1.75

# Cursor "Max Mode" doubles input rate past this threshold for some models.
MAX_MODE_INPUT_THRESHOLD = 200_000

# Teams plan: Cursor Token Rate adds $0.25 per 1M (input + output) tokens
# for non-Auto / non-Composer agent requests. Individual Pro plan does NOT
# pay this; document via flag, do not bake in.
TEAMS_TOKEN_RATE_PER_M = 0.25


def _is_thinking(model: dict, alias: str = "") -> bool:
    """Detect thinking-mode dispatch from cli_arg (or alias as fallback).

    Cursor encodes thinking variants as `<base>-thinking-<level>` (e.g.
    `claude-opus-4-7-thinking-high`, `claude-4.6-sonnet-medium-thinking`).
    Gemini 3.1 Pro on Cursor is always deep-thinking even without the
    `thinking` substring.

    When `cli_arg` is missing (some user-maintained models.json entries leave
    it null), fall back to the alias so the estimate doesn't silently
    under-count reasoning tokens for known thinking models.
    """
    cli = (model.get("cli_arg") or "").lower()
    if "thinking" in cli:
        return True
    if cli == "gemini-3.1-pro":
        return True
    a = alias.lower()
    if "thinking" in a:
        return True
    if a == "cursor-gemini-3.1-pro":
        return True
    return False


def _is_composer_or_auto(model: dict) -> bool:
    """Teams-plan exemption: Composer-* and Auto-* skip the Cursor Token Rate."""
    cli = (model.get("cli_arg") or "").lower()
    return "composer" in cli or cli.startswith("auto")


def _load_registry(registry_path: pathlib.Path) -> dict:
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"registry not found: {registry_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse {registry_path}: {exc}") from exc


PRICING_SOURCES = ("registry", "snapshot", "both")
_SNAPSHOT_DISAGREE_PCT = 10.0


def _resolve_pricing(model: dict, source: str) -> tuple[float, float, list[str]]:
    """Return (effective_per_1m_input, per_1m_output, notes) honouring `source`.

    `source` is one of registry|snapshot|both. Cursor pool models always fall
    back to the registry (LiteLLM has no Cursor keys, and the project's only
    source of truth is `models.json`). The notes list is appended verbatim
    to the user-facing estimate output so the resolution path is auditable.

    Cached input handling (audit P3.4): if registry has `per_1m_cached_input`
    and the env var `ROUNDTABLE_CACHE_HIT_RATIO` is set (default: 0.0), the
    effective input rate is blended:
        eff = (1 - ratio) * per_1m_input + ratio * per_1m_cached_input
    Set ROUNDTABLE_CACHE_HIT_RATIO=0.7 (typical agentic-loop hit rate) to
    factor cache savings into estimates. The default 0.0 keeps behavior
    backward-compatible (no cache discount applied).
    """
    import os as _os
    notes: list[str] = []
    pricing = model.get("pricing") or {}
    reg_in = float(pricing.get("per_1m_input") or 0.0)
    reg_out = float(pricing.get("per_1m_output") or 0.0)
    reg_cached_in = pricing.get("per_1m_cached_input")
    cache_ratio_str = _os.environ.get("ROUNDTABLE_CACHE_HIT_RATIO", "")
    cache_ratio = 0.0
    if cache_ratio_str:
        try:
            cache_ratio = max(0.0, min(1.0, float(cache_ratio_str)))
        except ValueError:
            notes.append(
                f"WARNING: ROUNDTABLE_CACHE_HIT_RATIO={cache_ratio_str!r} not a number; using 0."
            )
    if cache_ratio > 0 and reg_cached_in is not None and reg_in > 0:
        cached_in = float(reg_cached_in)
        eff_in = (1.0 - cache_ratio) * reg_in + cache_ratio * cached_in
        notes.append(
            f"Cache-blended input: {cache_ratio:.0%} hit rate × ${cached_in:.4f}/M "
            f"+ {1.0 - cache_ratio:.0%} × ${reg_in:.4f}/M = ${eff_in:.4f}/M effective."
        )
        reg_in = eff_in

    if source == "registry":
        return reg_in, reg_out, notes

    snap_in: float | None = None
    snap_out: float | None = None
    snap_id: str | None = None
    if _ps is not None:
        # The snapshot is keyed by LiteLLM canonical id, which matches our
        # `cli_arg` for non-Cursor models (e.g. `gpt-5.5`, `claude-opus-4-7`).
        # Cursor's `cli_arg` slugs (`composer-2-fast`, `claude-opus-4-7-thinking-high`)
        # are stub entries (_no_litellm_source: true) so this returns None
        # and we keep registry pricing.
        cli = model.get("cli_arg")
        if cli:
            snap = _ps.get_model_pricing(cli)
            if snap is not None:
                snap_in = snap["per_1m_input"]
                snap_out = snap["per_1m_output"]
                snap_id = snap.get("_litellm_id", cli)

    if source == "snapshot":
        if snap_in is None or snap_out is None:
            notes.append(
                "Pricing source: registry (snapshot has no entry for this model — "
                "expected for Cursor pool / proxy / DeepSeek BYOK rows)."
            )
            return reg_in, reg_out, notes
        notes.append(
            f"Pricing source: LiteLLM snapshot ({snap_id}); ${snap_in:.2f}/M in, "
            f"${snap_out:.2f}/M out."
        )
        return snap_in, snap_out, notes

    # both: prefer snapshot if available, but warn on > _SNAPSHOT_DISAGREE_PCT diff.
    if snap_in is None or snap_out is None:
        notes.append(
            "Pricing source: registry only (no LiteLLM snapshot entry; Cursor/proxy/BYOK)."
        )
        return reg_in, reg_out, notes

    def _pct(a: float, b: float) -> float:
        if b <= 0:
            return 0.0 if a == 0 else 100.0
        return abs(a - b) / b * 100.0

    in_drift = _pct(snap_in, reg_in) if reg_in > 0 else None
    out_drift = _pct(snap_out, reg_out) if reg_out > 0 else None
    big_drift = (
        (in_drift is not None and in_drift > _SNAPSHOT_DISAGREE_PCT)
        or (out_drift is not None and out_drift > _SNAPSHOT_DISAGREE_PCT)
    )
    if big_drift:
        notes.append(
            "WARNING: registry vs LiteLLM snapshot pricing disagree by "
            f">{_SNAPSHOT_DISAGREE_PCT:.0f}% "
            f"(registry: ${reg_in:.4f}/M in / ${reg_out:.4f}/M out; "
            f"snapshot: ${snap_in:.4f}/M in / ${snap_out:.4f}/M out). "
            "Refresh `scripts/lib/pricing_snapshot.json` or update `models.json`."
        )
    else:
        notes.append(
            f"Pricing source: LiteLLM snapshot ({snap_id}) — within "
            f"{_SNAPSHOT_DISAGREE_PCT:.0f}% of registry."
        )
    return snap_in, snap_out, notes


def _model_speed_tps(model: dict) -> tuple[float | None, str]:
    """Return (tokens_per_sec_median, source_label) or (None, 'unmeasured').

    Speed lives in `endpoint.speed.tokens_per_sec_median` for codex/claude
    (proxy speed; measured via scripts/lib/speed_test.py) and in top-level
    `speed.tokens_per_sec_median` for cursor-subagent (typically None — see
    note in registry).
    """
    ep_sp = (model.get("endpoint") or {}).get("speed") or {}
    if ep_sp.get("tokens_per_sec_median") is not None:
        return float(ep_sp["tokens_per_sec_median"]), "endpoint.speed"
    top_sp = model.get("speed") or {}
    if top_sp.get("tokens_per_sec_median") is not None:
        return float(top_sp["tokens_per_sec_median"]), "speed"
    return None, "unmeasured"


# Per-turn dispatch overhead (tool-loop control flow, parent orchestration,
# network round-trips before/after model emit). Derived from history aggregate
# 2026-05-11: smallest observed turns (effort=low, 1-2 tool calls) ~45s with
# ~200 emit tokens at ~34 tok/s → ~6s of emit + ~30s overhead + tool latency.
WALL_CLOCK_OVERHEAD_S = 30.0


def estimate(
    alias: str,
    role: str,
    *,
    turns: int = 1,
    effort: str = "medium",
    max_mode: bool = False,
    teams: bool = False,
    registry_path: pathlib.Path | None = None,
    source: str = "registry",
) -> dict:
    """Compute a per-dispatch USD band and return a structured result dict.

    Returns a dict with all numeric fields the text and JSON formatters need
    so callers can render either format from the same payload.
    """
    if turns < 1:
        raise SystemExit(f"--turns must be >= 1, got {turns}")
    if source not in PRICING_SOURCES:
        raise SystemExit(
            f"unknown pricing source: {source!r}; known: {list(PRICING_SOURCES)}"
        )
    budgets = ROLE_TOKEN_BUDGETS.get(role)
    if not budgets:
        raise SystemExit(
            f"unknown role: {role!r}; known: {sorted(ROLE_TOKEN_BUDGETS)}"
        )
    mult = EFFORT_MULTIPLIERS.get(effort)
    if not mult:
        raise SystemExit(
            f"unknown effort: {effort!r}; known: {sorted(EFFORT_MULTIPLIERS)}"
        )

    registry_path = registry_path or _default_registry()
    registry = _load_registry(registry_path)
    models = registry.get("models", {})
    model = models.get(alias)
    if not model:
        known = sorted(k for k in models if not k.startswith("_"))
        raise SystemExit(
            f"unknown model alias {alias!r} (registry: {registry_path.name}); "
            f"known: {known}"
        )

    thinking = _is_thinking(model, alias=alias)
    input_per_turn = int(round(budgets["input"] * mult["input"]))
    output_key = "output_thinking" if thinking else "output_chat"
    output_per_turn = int(round(budgets[output_key] * mult["output"]))

    per_in, per_out, source_notes = _resolve_pricing(model, source)

    effective_per_in = per_in
    if max_mode and input_per_turn > MAX_MODE_INPUT_THRESHOLD:
        effective_per_in = per_in * 2.0

    input_cost_per_turn = input_per_turn / 1_000_000.0 * effective_per_in
    output_cost_per_turn = output_per_turn / 1_000_000.0 * per_out

    teams_extra_per_turn = 0.0
    if teams and not _is_composer_or_auto(model):
        teams_extra_per_turn = (
            (input_per_turn + output_per_turn) / 1_000_000.0 * TEAMS_TOKEN_RATE_PER_M
        )

    point_per_turn = input_cost_per_turn + output_cost_per_turn + teams_extra_per_turn
    point = point_per_turn * turns
    low = point * LOW_BAND
    high = point * HIGH_BAND

    reasoning_tokens_per_turn = 0
    reasoning_share = 0.0
    if thinking and output_per_turn > 0:
        chat_baseline = int(round(budgets["output_chat"] * mult["output"]))
        reasoning_tokens_per_turn = max(0, output_per_turn - chat_baseline)
        reasoning_share = round(reasoning_tokens_per_turn / output_per_turn, 2)

    notes: list[str] = list(source_notes)
    if thinking:
        notes.append(
            "Thinking-mode output includes reasoning tokens; billed as output. "
            "Cursor charges thinking variants at the same /M rate but with 5-10x "
            "more output tokens per turn vs non-thinking."
        )
    if max_mode and effective_per_in != per_in:
        notes.append(
            f"Max Mode active: input rate doubled to ${effective_per_in:.2f}/M "
            f"(input p50 {input_per_turn:,} > {MAX_MODE_INPUT_THRESHOLD:,} threshold)."
        )
    if teams:
        if _is_composer_or_auto(model):
            notes.append(
                "Teams plan flag set, but Cursor Token Rate does not apply to "
                "Composer/Auto requests."
            )
        else:
            notes.append(
                f"Teams plan: Cursor Token Rate +${TEAMS_TOKEN_RATE_PER_M:.2f}/M "
                f"applied (input+output)."
            )
    else:
        notes.append(
            f"For Teams plan add Cursor Token Rate +${TEAMS_TOKEN_RATE_PER_M:.2f}/M "
            f"(use --teams). Individual Pro plan does NOT pay this."
        )
    notes.append(
        "Bands are heavy-tailed heuristics; recalibrate ROLE_TOKEN_BUDGETS "
        "quarterly against history/<role>/<ts>/ p50."
    )

    # ── Wall-clock estimate ─────────────────────────────────────────────────
    # Why: a "simple executor" turn dispatched against the slowest viable model
    # can take an hour. Cost band alone doesn't catch this — a $0.20 turn that
    # runs 3000s is still a UX disaster. Compute it from output_per_turn /
    # measured tokens/sec + dispatch overhead.
    #
    # output_per_turn already accounts for thinking via the EFFORT_MULTIPLIERS
    # output factor (high=1.8, xhigh=3.0), so we don't apply another effort
    # scale here. The measured tps is chat-mode (no explicit thinking flag) but
    # since GPT-5 series emits reasoning tokens by default during the same test,
    # the measured rate already reflects "real emit speed under thinking".
    tps_value, tps_source = _model_speed_tps(model)
    if tps_value is not None and tps_value > 0:
        point_s_per_turn = output_per_turn / tps_value + WALL_CLOCK_OVERHEAD_S
        wall_clock_s = {
            "point_per_turn": round(point_s_per_turn, 1),
            "low_per_turn": round(point_s_per_turn * LOW_BAND, 1),
            "high_per_turn": round(point_s_per_turn * HIGH_BAND, 1),
            "point_total": round(point_s_per_turn * turns, 1),
            "low_total": round(point_s_per_turn * turns * LOW_BAND, 1),
            "high_total": round(point_s_per_turn * turns * HIGH_BAND, 1),
            "tps_used": tps_value,
            "tps_source": tps_source,
            "overhead_s_per_turn": WALL_CLOCK_OVERHEAD_S,
            "note": ("Ceiling estimate — assumes the dispatch fills the role's "
                     "output token budget. Actual turns may stop earlier if the "
                     "model emits acceptance criteria sooner. Cross-check vs "
                     "history/<role>/ p50 if available."),
        }
        # Surface the ceiling prominently in notes when it's ugly.
        if point_s_per_turn >= 600:
            notes.insert(0, f"⚠ wall-clock CEILING ~{int(point_s_per_turn)}s per turn "
                            f"({tps_value:.0f} tok/s × {output_per_turn:,} output tokens). "
                            f"Pick a faster model or lower effort if this exceeds budget.")
    else:
        wall_clock_s = None
        notes.append(
            "Wall-clock estimate UNAVAILABLE — speed unmeasured for this model. "
            "Run scripts/lib/speed_test.py to populate endpoint.speed (codex/claude) "
            "or dispatch a measurement Task subagent (cursor-subagent)."
        )

    return {
        "model_alias": alias,
        "cli_arg": model.get("cli_arg"),
        "actor": model.get("actor"),
        "role": role,
        "turns": turns,
        "effort": effort,
        "thinking": thinking,
        "input_tokens_p50": input_per_turn * turns,
        "output_tokens_p50": output_per_turn * turns,
        "input_tokens_per_turn": input_per_turn,
        "output_tokens_per_turn": output_per_turn,
        "input_cost_usd": round(input_cost_per_turn * turns, 4),
        "output_cost_usd": round(output_cost_per_turn * turns, 4),
        "teams_extra_usd": round(teams_extra_per_turn * turns, 4),
        "estimate_usd": {
            "point": round(point, 2),
            "low": round(low, 2),
            "high": round(high, 2),
        },
        "reasoning_tokens": reasoning_tokens_per_turn * turns,
        "reasoning_share": reasoning_share,
        "per_1m_input": per_in,
        "per_1m_output": per_out,
        "effective_per_1m_input": effective_per_in,
        "max_mode": bool(max_mode),
        "teams": bool(teams),
        "registry": registry_path.name,
        "pricing_source": source,
        "wall_clock_s": wall_clock_s,
        "notes": notes,
    }


def _fmt_tokens(n: int) -> str:
    return f"{n:,}"


def _fmt_short(n: int) -> str:
    """Compact rendering: 80000 → 80k, 1500000 → 1.5M."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}k"
    return str(n)


def format_text(result: dict) -> str:
    cli = result.get("cli_arg") or "?"
    turns = result["turns"]
    per = "per turn" if turns == 1 else f"for {turns} turns"
    lines = [
        f"Model:    {result['model_alias']}  ({cli})",
        f"Role:     {result['role']}",
        f"Turns:    {turns}",
        f"Effort:   {result['effort']}",
        (
            f"Estimate: ${result['estimate_usd']['low']:.2f} – "
            f"${result['estimate_usd']['high']:.2f} {per}  "
            f"(point: ${result['estimate_usd']['point']:.2f})"
        ),
        (
            f"  Input p50:      {_fmt_tokens(result['input_tokens_p50'])} tokens   "
            f"(${result['effective_per_1m_input']:.2f}/M)   "
            f"= ${result['input_cost_usd']:.2f}"
        ),
        (
            f"  Output p50:     {_fmt_tokens(result['output_tokens_p50'])} tokens   "
            f"(${result['per_1m_output']:.2f}/M)  "
            f"= ${result['output_cost_usd']:.2f}"
        ),
    ]
    if result["thinking"] and result["reasoning_tokens"] > 0:
        share_pct = int(round(result["reasoning_share"] * 100))
        lines.append(
            f"    of which reasoning:  ~{_fmt_tokens(result['reasoning_tokens'])} "
            f"tokens (≈{share_pct}%)"
        )
    wc = result.get("wall_clock_s")
    if wc:
        per = "per turn" if turns == 1 else f"for {turns} turns"
        lines.append(
            f"Wall-clock ceiling: ~{wc['low_total']:.0f}–{wc['high_total']:.0f}s {per}  "
            f"(point: ~{wc['point_total']:.0f}s @ {wc['tps_used']:.0f} tok/s)"
        )
    elif "wall_clock_s" in result:
        lines.append("Wall-clock ceiling: UNAVAILABLE (speed unmeasured for this model)")
    if result["teams"] and result["teams_extra_usd"] > 0:
        lines.append(
            f"  Teams Token Rate:                          "
            f"+${result['teams_extra_usd']:.2f}"
        )
    lines.append("Notes:")
    for n in result["notes"]:
        lines.append(f"  - {n}")
    return "\n".join(lines)


def format_json(result: dict) -> str:
    """Machine-readable subset matching the schema documented in the file header."""
    payload = {
        "model": result["model_alias"],
        "cli_arg": result["cli_arg"],
        "role": result["role"],
        "turns": result["turns"],
        "effort": result["effort"],
        "thinking": result["thinking"],
        "estimate_usd": result["estimate_usd"],
        "breakdown": {
            "input_tokens_p50": result["input_tokens_p50"],
            "output_tokens_p50": result["output_tokens_p50"],
            "input_cost_usd": result["input_cost_usd"],
            "output_cost_usd": result["output_cost_usd"],
            "teams_extra_usd": result["teams_extra_usd"],
            "reasoning_tokens": result["reasoning_tokens"],
            "reasoning_share": result["reasoning_share"],
            "per_1m_input": result["per_1m_input"],
            "effective_per_1m_input": result["effective_per_1m_input"],
            "per_1m_output": result["per_1m_output"],
        },
        "max_mode": result["max_mode"],
        "teams": result["teams"],
        "registry": result["registry"],
        "pricing_source": result.get("pricing_source", "registry"),
        "notes": result["notes"],
    }
    return json.dumps(payload, indent=2)


def format_route_line(result: dict) -> str:
    """One-line band suitable for embedding under a route.sh candidate row."""
    band = result["estimate_usd"]
    inp = _fmt_short(result["input_tokens_per_turn"])
    out = _fmt_short(result["output_tokens_per_turn"])
    extra = ""
    if result["thinking"] and result["reasoning_tokens"] > 0:
        # reasoning_tokens is summed over turns; show per-turn for the route line
        per_turn_reasoning = result["reasoning_tokens"] // max(1, result["turns"])
        extra = f" incl. ~{_fmt_short(per_turn_reasoning)} reasoning"
    wc = result.get("wall_clock_s")
    if wc:
        wc_part = (f"  ~{wc['low_per_turn']:.0f}–{wc['high_per_turn']:.0f}s "
                   f"@ {wc['tps_used']:.0f}tok/s")
    else:
        wc_part = "  ~?s (speed unmeasured)"
    return (
        f"   est: ${band['low']:.2f}–${band['high']:.2f}/turn  "
        f"(input p50: {inp}, output p50: {out}{extra}){wc_part}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Heuristic per-turn USD cost estimator. Buckets live at the top of "
            "this file (ROLE_TOKEN_BUDGETS / EFFORT_MULTIPLIERS) and are the "
            "auditable contract — patch with a dated NOTE if observed turns "
            "drift from the table."
        ),
    )
    parser.add_argument("--model", required=True, help="model alias from models.json")
    parser.add_argument(
        "--role",
        required=True,
        choices=sorted(ROLE_TOKEN_BUDGETS),
        help="role bucket (planner|executor|reviewer|devils-advocate|reviewer-aggregator|discussant)",
    )
    parser.add_argument("--turns", type=int, default=1)
    parser.add_argument(
        "--effort",
        choices=sorted(EFFORT_MULTIPLIERS),
        default="medium",
    )
    parser.add_argument(
        "--max-mode",
        action="store_true",
        help="Cursor Max Mode: 2x input rate when input p50 > 200k tokens.",
    )
    parser.add_argument(
        "--teams",
        action="store_true",
        help="Apply Cursor Teams Token Rate +$0.25/M (skipped for Composer/Auto).",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--registry",
        default=None,
        help="explicit path to a models.json-style registry (overrides default lookup)",
    )
    parser.add_argument(
        "--source",
        choices=list(PRICING_SOURCES),
        default="registry",
        help=(
            "Pricing source: 'registry' (models.json default), 'snapshot' "
            "(scripts/lib/pricing_snapshot.json — vendored LiteLLM whitelist), "
            "or 'both' (snapshot when present, warn if registry/snapshot diverge "
            f">{int(_SNAPSHOT_DISAGREE_PCT)}%)."
        ),
    )
    args = parser.parse_args(argv)

    registry_path = pathlib.Path(args.registry) if args.registry else None
    result = estimate(
        args.model,
        args.role,
        turns=args.turns,
        effort=args.effort,
        max_mode=args.max_mode,
        teams=args.teams,
        registry_path=registry_path,
        source=args.source,
    )
    if args.json:
        print(format_json(result))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
