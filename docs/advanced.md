# Agent Roundtable — Advanced Usage

Reference material for signal-based routing, parallel dispatch patterns, convergence loops, and Cursor Task subagent integration. The core protocol lives in [../SKILL.md](../SKILL.md).

## Model registry & signal-based routing

`<SKILL_DIR>/models.json` is the single source of truth. Per-model entries include `actor`, `cli_arg`, `context_window_k`, `max_output_k`, `benchmarks` (verified scores), `best_for`, and `pricing`. `role_defaults[<role>]` provides the base ordering.

`scripts/route.sh --role <role>` reads `models.json`, detects available actors, applies optional task signals, and prints ranked candidates with benchmark scores and pricing:

```bash
route.sh --role reviewer                              # default ordering
route.sh --role reviewer --budget cheap               # sort by cost ascending
route.sh --role executor --latency fast               # exclude cursor-subagent
route.sh --role executor --output-heavy               # exclude models with max_output < 128K
route.sh --role reviewer --budget premium --json      # sort by benchmark score, JSON output
```

**Recommendations are advisory; the user always picks.**

### Adding / retuning a model

1. Add an entry under `models.<alias>` with `actor`, `cli_arg`, `context_window_k`, `max_output_k`, `benchmarks`, `pricing`.
2. (Optional) Adjust `role_defaults.<role>` to insert/promote/demote that alias.

## Dispatching a Cursor Task subagent

When `route.sh` recommends a `cursor-subagent` actor, the chat parent (not a shell script) does the work:

1. Note the recommended `cli_arg` (e.g. `claude-opus-4-7-thinking-high`).
2. Invoke the `Task` tool with the matching `subagent_type` (`generalPurpose`, `explore`, `gsd-*`, `code-reviewer`, …) and that `model`. The prompt MUST instruct the subagent to produce the standard 5-part turn body as its **final assistant message**.
3. Capture the Task output to a local file (e.g. `/tmp/turn-body.md`).
4. Append it via `scripts/append_turn.sh <slug> --actor cursor-subagent --role <role> --model <alias> --task-subagent-type <type> --body-file /tmp/turn-body.md --prompt-file /tmp/prompt.md` (with optional `--tokens-in/-out --duration-s`).

This appends the turn, writes `meta.json` (with `task_subagent_type`), extracts `verdict.json` for reviewer roles, and emits the standard `ROUNDTABLE_DONE: …` completion signal — same contract as `codex_turn.sh` / `claude_turn.sh`.

## Parallel dispatch

Use **Cursor's native parallel tool calls** — NOT `nohup &` or shell `&`+`wait`.

### Pattern A — two CLI agents in parallel

The chat parent sends TWO Shell tool calls in a single message, each blocking:

```
Shell call 1:  bash $SKILL/scripts/codex_turn.sh  my-thread --role reviewer …   [block_until_ms: 1800000]
Shell call 2:  bash $SKILL/scripts/claude_turn.sh my-thread --role reviewer …   [block_until_ms: 1800000]
```

Both auto-background. Each gets its own task_id with an independent `ROUNDTABLE_DONE:` signal. Use `AwaitShell --pattern "ROUNDTABLE_DONE:"` on each task_id when needed.

### Pattern B — CLI + cursor-subagent in parallel

```
Shell call:  bash $SKILL/scripts/codex_turn.sh  my-thread --role reviewer …    [block_until_ms: 1800000]
Task call:   Task(subagent_type="generalPurpose", run_in_background=true, …)
```

The Shell produces `ROUNDTABLE_DONE:`. The Task produces a system notification on completion; the chat parent then runs `append_turn.sh` to land its body into `THREAD.md`.

### Pattern C — two cursor-subagents in parallel

Two `Task(run_in_background=true)` calls in one message.

### Why not `&`+`wait` in a single shell?

Shell `&` forks to background; Cursor's Shell tool sees the parent exit immediately (same problem as `nohup`). Interleaved stdout also makes `ROUNDTABLE_DONE:` parsing unreliable. Always use separate tool calls.

The reviewer schema (`roles/reviewer.schema.json`) requires a `dissenting_concerns` field on the aggregator's verdict — preserve dissent, don't average it away.

## Convergence-loop mode

For "iterate to convergence" / "loop until done": after one initial user confirmation, the parent runs `executor → reviewer → decide` rounds until DoD passes or budget (`MAX_ITER`, `MAX_WALL_MIN`) is exhausted. Reviewer JSON may add optional `convergence_status` (`converged | progressing | stalled | regressed | unknown`) and `next_action_hint`. Stop on 2 consecutive `stalled` (escalate), 2× `regressed` (revert + ask), or sacred-boundary blocker.

## Dispatch & turn-completion signals

**Do NOT use `nohup ... &`.** Run the script directly so the shell blocks until it finishes:

```bash
bash scripts/codex_turn.sh  my-thread --role executor -m <your-codex-alias>  [block_until_ms: 1800000]
bash scripts/claude_turn.sh my-thread --role reviewer --model <your-claude-alias> [block_until_ms: 1800000]
```

If the script finishes before `block_until_ms` the Shell tool returns with `ROUNDTABLE_DONE:` in the output. If it takes longer the Shell is backgrounded — use `AwaitShell --pattern "ROUNDTABLE_DONE:"` to wait.

Every turn script emits **two completion signals**:

1. **STDOUT marker** — the LAST stdout line: `ROUNDTABLE_DONE: thread=<slug> actor=<…> role=<…> exit=<N> turn=<N> duration_s=<N>`.
2. **Sentinel file** — `<history_dir>/.done` written with the same payload + `ts=<ISO8601>`.

> **Why not `nohup &` + `block_until_ms: 0`?** The `nohup` launcher exits in ~100 ms; any "task completed" notification from Cursor fires for the launcher exit, not the actual agent work. `ROUNDTABLE_DONE:` would never appear in the shell output.

## Operational notes

- **Token efficiency**: `build_prompt` inlines the last `ROUNDTABLE_TAIL_K` turns (default 3); Verification blocks in recent turns are auto-truncated at `ROUNDTABLE_VERIFICATION_LIMIT` chars (default 1000). Discipline reminders auto-skip when role system prompt exists. For long threads run `compact_thread.sh <slug> --keep 6`.
- **Reviewer JSON verdict**: extracted automatically as `history/<actor>/<ts>/verdict.json`.
- **Tool whitelisting (claude)**: `--allowed-tools` fully replaces both allowlist and disallowlist.
- **Goal bridge (codex only)**: executor turns inject a `/goal bridge` addendum that hooks into codex's `get_goal`/`create_goal`/`update_goal` tools. Claude Code does not have goal tools — the bridge is codex-exclusive.

## Known sharp edges

1. **Cursor `Task` latency is unbounded.** Pool throttling can queue 10+ min. Prefer CLI when wallclock matters.
2. **Addendum/body files must be under workspace root**, not `/tmp/` (Cursor's subprocess `/tmp` is isolated).

## N parallel executors (race) — opt-in

The default `roundtable-execute` skill is **single executor**. Use this pattern only when multiple candidate implementations are worth the cost (extra branches, aggregator turn, forensic loser branches).

### When it helps

- Multiple high-quality candidate implementations are genuinely valuable: risky changes where seeing different shapes informs the merge decision.
- Speed-via-racing: N× tokens to compress wallclock.
- Prior single-executor attempts produced a working-but-ugly answer and alternative shapes are worth comparing.

### Process sketch

1. **Confirm dispatch** — show Dispatch Confirmation; sum per-actor estimates across N executors.
2. **Isolate worktrees** — each executor gets its own branch via `git worktree`. Same `--task` and `GOAL.md`; executors do not read each other’s trees.

```bash
slug=<thread-slug>
git -C $ROUNDTABLE_PROJECT_ROOT worktree add ../$slug-codex   -b $slug/codex
git -C $ROUNDTABLE_PROJECT_ROOT worktree add ../$slug-claude  -b $slug/claude

ROUNDTABLE_PROJECT_ROOT=../$slug-codex   $SKILL/scripts/codex_turn.sh  $slug --role executor --task "<same one-liner>"
ROUNDTABLE_PROJECT_ROOT=../$slug-claude  $SKILL/scripts/claude_turn.sh $slug --role executor --task "<same one-liner>"
```

Run concurrent Shell/Task dispatches (see [Parallel dispatch](#parallel-dispatch) above). All N must finish before aggregation.

3. **Aggregator picks one winner** — use `roundtable-review`’s aggregator contract; instruct **select**, not Frankenstein merge:

```bash
$SKILL/scripts/claude_turn.sh $slug --role reviewer-aggregator \
  --task "Compare candidate branches: $slug/codex, $slug/claude (…). Select the SINGLE best candidate. Justify by evidence_delta against GOAL.md. Do NOT propose a merged chimera; pick one branch as-is."
```

4. **Hand off** — surface the winning branch, verdict path, and loser SHAs; keep loser branches as record.

### Red flags

- Same actor family for all parallel executors — fails independence premise; diversify vendors.
- Aggregator synthesizes a merge instead of picking one branch — re-dispatch with stricter framing.

---

## Single-vendor parallel via Codex `spawn_agent` (opt-in)

Codex 0.128+ ships a native `[agents]` config + `spawn_agent` tool that lets a parent Codex turn fan out to multiple Codex sub-agents inside one process. This is **cheaper than the cross-vendor pattern** in §"N parallel executors" because (a) only one CLI is dispatched, (b) the parent shares prompt cache with its children, (c) no per-vendor auth boot tax. **It is opt-in** and the roundtable main path does NOT use it — by design, because the cross-vendor diversity that defends against modal sycophancy (≥85% adoption when reviewers share an actor family) is precisely what `spawn_agent` gives up.

### When `spawn_agent` is the right tool

- The parallelism is for **search / coverage**, not for **independence**. Examples: enumerate N candidate refactors of one file, generate N test variations, fan out across N independent files in a large rename — tasks where single-vendor agreement is fine and cheaper > diverse.
- You do **not** need a reviewer-aggregator after the fan-out. (If you do, prefer cross-vendor.)
- Wallclock matters and the task fits in Codex's session budget.

### When NOT to use `spawn_agent` (use the cross-vendor pattern)

- Reviewing for sycophancy / consensus-collapse risk — needs heterogeneous reviewers, see [Cost of Consensus, 2025](https://arxiv.org/html/2605.00914v1).
- Planning where you want option diversity — Phase A of `roundtable-plan` exists exactly to break single-actor framing.
- Anything where the failure mode "every agent missed the same thing because they share priors" would be costly.

### Wiring sketch (advanced — read Codex docs first)

`~/.codex/config.toml` registers child agent profiles; the parent invokes them via the `spawn_agent` tool. Roundtable does not orchestrate this — write a one-off prompt that asks the Codex executor to call `spawn_agent` N times and collect results, then run a normal `codex_turn.sh` executor with that prompt as `--task`. Capture children's output through the parent's `last.md`; do **not** try to reverse-engineer child history into per-actor THREAD.md entries (would break independence accounting).

### Cost trade-off (rule of thumb)

| Pattern | Approx. token cost | Diversity defence |
|---|---|---|
| `roundtable-execute` cross-vendor race (N=2) | ~2× single executor + aggregator overhead | Strong — different actor families |
| `spawn_agent` single-vendor fan-out (N=2) | ~1.2–1.4× single executor (cache reuse) | None — same actor, same priors |

If in doubt, prefer the cross-vendor path. `spawn_agent` is for users who have already paid the diligence cost of confirming their task does not need diversity.

---

## Evidence — when multi-agent helps

- Cross-vendor review outperforms same-vendor: same-actor parallel reviewers exhibit ≥85% sycophantic modal adoption ([Cost of Consensus, 2025](https://arxiv.org/html/2605.00914v1)). Heterogeneous reviewers preserve disagreement ([Preserving Disagreement, 2025](https://arxiv.org/html/2604.26561)).
- Homogeneous multi-agent debate costs 2–3× more tokens for equal or worse accuracy vs single-agent self-correction. One good turn beats three mediocre parallel ones.
- The `dissenting_concerns` field in `reviewer.schema.json` exists to preserve minority dissent against consensus collapse.

---

## Polling outside Cursor (wait_for_done.sh)

When running turn scripts outside the Cursor IDE — in CI, from a remote terminal, or in a cron job — `AwaitShell` is unavailable. Use `scripts/wait_for_done.sh` instead:

```bash
# Start a turn in the background
bash scripts/claude_turn.sh my-thread --role executor --task "..." &

# Poll for completion (checks for .done sentinel file)
bash scripts/wait_for_done.sh my-thread
echo "Turn complete, exit code: $?"
```

`wait_for_done.sh` polls `<thread_dir>/.done` every 5 seconds and exits with the turn's exit code. Use `--timeout-s 1800` to set a max wait (default: 3600s).

---

## Future work

The following features are designed but not yet implemented:

**Automatic failover.** When a turn fails due to rate-limit, timeout, or stall, `_common.sh:dispatch_with_fallback` would walk each model's `fallback_chain` (defined in `models.json`) and re-dispatch, logging each hop to `<thread_dir>/THREAD_LEDGER.md`. Opt-in via `ROUNDTABLE_FAILOVER_OPT_IN=1`. Until implemented, retry failed turns manually.
