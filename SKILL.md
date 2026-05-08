---
name: agent-roundtable
description: Multi-agent collaboration substrate for working with the user, Cursor (chat parent), Codex CLI, and Claude Code as peers around a shared on-disk thread. Use when the user wants two or more agents to plan/execute/review/discuss together, when delegating tasks to codex or claude as subagents, when iterating with the user across multiple rounds, or when the user mentions roundtable / 多智能体协作 / 让 codex/claude 一起干 / cross-agent review. Each turn is appended to a single THREAD.md so any agent (or the user) can pick up the next turn with full context.
---

# Agent Roundtable

A thin file-based substrate, not a framework. Participants take turns around a shared on-disk thread under `$ROUNDTABLE_ROOT/threads/<slug>/` (default `<repo>/.roundtable/threads/<slug>/`). The protocol fits in one page; the value is the audit trail, not the scripts.

> **Don't over-reach.** For a single-CLI task, just call `codex exec` or `claude -p` directly. Use roundtable when you specifically want (a) two+ different CLIs working on the same goal, or (b) a durable on-disk record any agent or human can pick up. Multi-agent debate has [documented failure modes](#evidence--when-multi-agent-actually-helps); don't reach for it reflexively.

## Architecture — who does what

| Role | Who | Dispatched how |
|---|---|---|
| **Chat parent** (orchestration / discussion / summary with the user) | The model running the IDE conversation (e.g. Claude 4.7 Opus in Cursor). **Stays on the main thread; never a dispatch target.** | Implicit — always present. |
| **Cursor subagent** | Composer 2 / Claude 4.7 Opus / Claude 4.6 Opus / Sonnet / GPT-5.5 / GPT-5.4 / Gemini 3.1 Pro via Cursor's `Task` tool. | Chat parent calls `Task(subagent_type=…, model=<slug>, prompt=…)`, then `scripts/append_turn.sh` appends the result to `THREAD.md`. |
| **Codex CLI** | gpt-5.5 / gpt-5.4 / gpt-5.4-mini / gpt-5.3-codex via [cialloapi.cn](https://cialloapi.cn/pricing) proxy. | `scripts/codex_turn.sh <slug> --role <r> -m <model>`. |
| **Claude CLI** | DeepSeek-V4-Pro (`opus`/`sonnet`) and DeepSeek-V4-Flash (`haiku`) via DeepSeek API. **These are NOT Anthropic models** — aliases are CLI-compat shims. | `scripts/claude_turn.sh <slug> --role <r> --model <alias>`. |

Any dispatchable participant can play any role on any turn — planner, executor, reviewer, discussant. The chat parent decides who plays what (with `route.sh` as a hint) after confirming with the user.

## Setup

- **Env**: `ROUNDTABLE_REPO_ROOT` (git root, auto-detected), `ROUNDTABLE_ROOT` (default `$ROUNDTABLE_REPO_ROOT/.roundtable`), `ROUNDTABLE_TAIL_K` (recent turns inlined into prompts; default `3`).
- **Auth**: run `codex login status` and `claude auth status` once before first use; this skill does not log in for you.
- **Per-actor backend override** (optional): copy `<SKILL_DIR>/.<actor>_env.example` → `.<actor>_env.local` (gitignored) to point one CLI at a non-default proxy/key. The relevant `*_turn.sh` sources it inside its own subprocess only, so your interactive CLI sessions are unaffected. Templates exist for `claude` and `codex`. Skip entirely if your shell env / `~/.codex/auth.json` already point where you want roundtable to go.
- Tested on Linux with Codex CLI ≥ 0.128 and Claude Code ≥ 2.1.126.

## Thread layout

```
$ROUNDTABLE_ROOT/threads/<slug>/
├── THREAD.md              # five-part turn timeline (append-only)
├── THREAD_SUMMARY.md      # compacted older turns (created by compact_thread.sh)
├── GOAL.md                # goal / DoD / scope / verification commands
├── OPEN_QUESTIONS.md
├── artifacts/             # outputs from any role (planner/discussant/executor)
├── history/<actor>/<ts>/  # prompt.md, last.md, trace.jsonl, meta.json, verdict.json, .done
└── worktrees/<name>/      # optional git worktrees
```

`<repo>/.roundtable/threads/latest` is a symlink to the most recent thread (auto-maintained).

## Five-part turn body (mandatory)

Every turn appended to `THREAD.md` MUST be exactly:

```
**Read**: <files opened, abs path + line range>
**Did**: <what was done, bulleted>
**Verification**: <commands run + outcomes; reviewer role embeds the structured JSON verdict>
**Open questions**: <new ambiguities>
**Hand-off**: <accept | revise: <who> on <what> | escalate-to-user: <q>>
```

Dispatchers capture this final assistant message verbatim (`codex -o last.md`, `claude .result`) and append it as the next numbered turn.

## Hard rules

1. **Confirm dispatch**: default is to ask the user (which agent, model, effort) before each dispatch. Skip the confirmation in convergence-loop mode and other pre-agreed workflows.
2. **Single writer per path**: no two agents write to the same file concurrently. Parallel turns require disjoint file ownership, separate worktrees, or all-but-one read-only roles.
3. **No agent recursion**: only the user and chat parent orchestrate. Codex must not invoke claude or cursor-agent; claude must not invoke codex.
4. **Self-contained prompts**: subagents see no chat history — the dispatch script injects context (THREAD.md tail + GOAL.md + role guidelines + addendum) fresh each turn.
5. **Acceptance evidence**: reviewer turns must produce the structured JSON verdict per `roles/reviewer.schema.json`. "Looks good" is not a review.
6. **Cross-vendor review**: for multi-reviewer turns prefer different actors (codex + claude + cursor-subagent). Same-actor reviewers exhibit sycophantic conformity.
7. **English on disk**: all on-disk artifacts (THREAD.md, GOAL.md, OPEN_QUESTIONS.md, addenda, artifacts/, reviewer JSON) must be in English. `build_prompt` injects this automatically. Translate Chinese GOAL.md content before dispatch (keep the original as a quoted block + gloss). User-facing chat replies in Chinese live in `.cursor/rules/language.md`, not here.

## Scripts

All under `<SKILL_DIR>/scripts/` and executable.

| Script | Purpose | Notable flags |
|---|---|---|
| `new_thread.sh <slug> "<goal>"` | Initialise thread layout + `latest` symlink. | — |
| `codex_turn.sh <slug> --role ROLE` | One `codex exec` turn. Salvages `last.md` from `trace.jsonl` if codex doesn't flush. | `-m`, `--effort`, `--sandbox`, `--worktree`, `--addendum[-file]`, `--timeout-s` |
| `claude_turn.sh <slug> --role ROLE` | One `claude -p` turn. Auto-attaches `roles/<role>.system.md` via `--append-system-prompt`. | `--model`, `--effort`, `--permission-mode`, `--bare`, `--worktree`, `--allowed-tools`, `--addendum[-file]` |
| `append_turn.sh <slug>` | Land a Cursor Task subagent's body into `THREAD.md`. | `--actor cursor-subagent`, `--role`, `--model`, `--body-file`, `--prompt-file`, `--tokens-in/-out` |
| `compact_thread.sh <slug>` | Compact old turns into `THREAD_SUMMARY.md`; keep last K turns in `THREAD.md`. | `--keep K` (default 6), `--dry-run` |
| `route.sh --role ROLE` | Signal-based routing: rank models by role defaults + task signals. | `--top N`, `--json`, `--cursor-subagent`, `--budget`, `--latency`, `--output-heavy` |

For a one-shot diff review without thread integration, just call `codex exec review --uncommitted|--base|--commit` directly — no wrapper needed.

## Role × default sandbox / permission

| Role | codex (cwd; sandbox) | claude (`--permission-mode`) | Notes |
|---|---|---|---|
| **planner** | thread-dir; workspace-write | acceptEdits | Can write `artifacts/plan.md`. Read-only w.r.t. source code. |
| **executor** | repo-root; workspace-write | acceptEdits + git-destructive disallowed | Only one executor per path at a time. |
| **reviewer** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Produces structured JSON verdict. Should not write source. |
| **reviewer-aggregator** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Merges N parallel reviewers into one canonical turn. |
| **discussant** | thread-dir; workspace-write | acceptEdits | Drafts options into `artifacts/`, adds to `OPEN_QUESTIONS.md`. |

Codex non-executor roles set `cwd=<thread-dir>` so `-s workspace-write` allows writes to `<thread-dir>/artifacts/` only; source code is read-only via `--add-dir <repo-root>`. Executor flips it (cwd=repo-root) to allow source edits.

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

### Dispatching a Cursor Task subagent

When `route.sh` recommends a `cursor-subagent` actor, the chat parent (not a shell script) does the work:

1. Note the recommended `cli_arg` (e.g. `claude-opus-4-7-thinking-xhigh`).
2. Invoke the `Task` tool with the matching `subagent_type` (`generalPurpose`, `explore`, `gsd-*`, `code-reviewer`, …) and that `model`. The prompt MUST instruct the subagent to produce the standard 5-part turn body as its **final assistant message**.
3. Capture the Task output to a local file (e.g. `/tmp/turn-body.md`).
4. Append it via `scripts/append_turn.sh <slug> --actor cursor-subagent --role <role> --model <alias> --task-subagent-type <type> --body-file /tmp/turn-body.md --prompt-file /tmp/prompt.md` (with optional `--tokens-in/-out --duration-s`).

This appends the turn, writes `meta.json` (with `task_subagent_type`), extracts `verdict.json` for reviewer roles, and emits the standard `ROUNDTABLE_DONE: …` completion signal — same contract as `codex_turn.sh` / `claude_turn.sh`.

## Parallel dispatch

Use **Cursor's native parallel tool calls** — NOT `nohup &` or shell `&`+`wait`.

**Pattern A — two CLI agents in parallel** (e.g. MARS multi-reviewer):
The chat parent sends TWO Shell tool calls in a single message, each blocking:

```
Shell call 1:  bash $SKILL/scripts/codex_turn.sh  my-thread --role reviewer …   [block_until_ms: 1800000]
Shell call 2:  bash $SKILL/scripts/claude_turn.sh my-thread --role reviewer …   [block_until_ms: 1800000]
```

Both auto-background. Each gets its own task_id with an independent `ROUNDTABLE_DONE:` signal. Use `AwaitShell --pattern "ROUNDTABLE_DONE:"` on each task_id when needed.

**Pattern B — CLI + cursor-subagent in parallel**:

```
Shell call:  bash $SKILL/scripts/codex_turn.sh  my-thread --role reviewer …    [block_until_ms: 1800000]
Task call:   Task(subagent_type="generalPurpose", run_in_background=true, …)
```

The Shell produces `ROUNDTABLE_DONE:`. The Task produces a system notification on completion; the chat parent then runs `append_turn.sh` to land its body into `THREAD.md`.

**Pattern C — two cursor-subagents in parallel**: two `Task(run_in_background=true)` calls in one message.

> **Why not `&`+`wait` in a single shell?** Shell `&` forks to background; Cursor's Shell tool sees the parent exit immediately (same problem as `nohup`). Interleaved stdout also makes `ROUNDTABLE_DONE:` parsing unreliable. Always use separate tool calls.

The reviewer schema (`roles/reviewer.schema.json`) requires a `dissenting_concerns` field on the aggregator's verdict — preserve dissent, don't average it away.

## Pre-dispatch micro-prompt to user

```
Next turn proposal (route.sh top pick: <actor>/<alias>):
  agent:    codex | claude | both-in-parallel | cursor-subagent (Task)
  role:     planner | executor | reviewer | discussant
  model:    <suggested cli_arg>     (alternates: …)
  effort:   <low|medium|high>
  worktree: none | <name>
  addendum: <one-line specific ask>
OK to dispatch? (or override any field)
```

Convergence-loop mode skips this between rounds — only checks in at loop start, on stall, on budget exhaustion, or on convergence.

## Skill activation per actor

| Actor | Skill catalogue | Activate by |
|---|---|---|
| cursor (chat parent) | `Task` subagents, MCP tools, this skill | parent picks subagent type per task |
| codex | `~/.codex/skills/` (`systematic-debugging`, `test-driven-development`, `executing-plans`, …) | inject "Use <skill>" by role |
| claude | `CLAUDE.md` + `~/.claude/skills/` | inject "Read and follow <skill>.md" by role |

Naming the skill is enough; do not paste full skill bodies into the addendum.

## Convergence-loop mode

For "iterate to convergence" / "loop until done": after one initial user confirmation, the parent runs `executor → reviewer → decide` rounds until DoD passes or budget (`MAX_ITER`, `MAX_WALL_MIN`) is exhausted. Reviewer JSON may add optional `convergence_status` (`converged | progressing | stalled | regressed | unknown`) and `next_action_hint`. Stop on 2 consecutive `stalled` (escalate), 2× `regressed` (revert + ask), or sacred-boundary blocker.

## Dispatch & turn-completion signals

**Do NOT use `nohup ... &`.** Run the script directly so the shell blocks until it finishes:

```bash
# Correct — blocking. Shell returns only when script emits ROUNDTABLE_DONE:.
bash scripts/codex_turn.sh  my-thread --role executor -m gpt-5.5  [block_until_ms: 1800000]
bash scripts/claude_turn.sh my-thread --role reviewer --model opus [block_until_ms: 1800000]
```

If the script finishes before `block_until_ms` the Shell tool returns with `ROUNDTABLE_DONE:` in the output. If it takes longer the Shell is backgrounded — use `AwaitShell --pattern "ROUNDTABLE_DONE:"` to wait.

Every turn script emits **two completion signals**:

1. **STDOUT marker** — the LAST stdout line: `ROUNDTABLE_DONE: thread=<slug> actor=<…> role=<…> exit=<N> turn=<N> duration_s=<N>`.
2. **Sentinel file** — `<history_dir>/.done` written with the same payload + `ts=<ISO8601>`.

> **Why not `nohup &` + `block_until_ms: 0`?** The `nohup` launcher exits in ~100 ms; any "task completed" notification from Cursor fires for the launcher exit, not the actual agent work. `ROUNDTABLE_DONE:` would never appear in the shell output.

## Reporting back (parent → user)

```
Turn N appended (actor=…, role=…, model=…, effort=…, exit=…, dur=…s).
Summary: <≤3 lines from the turn body>.
Verdict (if reviewer): <PASS/FAIL + top blockers>.
Files changed: <git diff --stat one-liner>.
Open questions now: <count + top one>.
Suggested next turn: <one proposal>.
```

## Evidence — when multi-agent helps

- Cross-vendor review outperforms same-vendor: same-actor parallel reviewers exhibit ≥85% sycophantic modal adoption ([Cost of Consensus, 2025](https://arxiv.org/html/2605.00914v1)). Heterogeneous reviewers preserve disagreement ([Preserving Disagreement, 2025](https://arxiv.org/html/2604.26561)).
- Homogeneous multi-agent debate costs 2–3× more tokens for equal or worse accuracy vs single-agent self-correction. One good turn beats three mediocre parallel ones.
- The `dissenting_concerns` field in `reviewer.schema.json` exists to preserve minority dissent against consensus collapse.

## Operational notes

- **Token efficiency**: `build_prompt` inlines the last `ROUNDTABLE_TAIL_K` turns (default 3); Verification blocks in recent turns are auto-truncated at `ROUNDTABLE_VERIFICATION_LIMIT` chars (default 1000). Discipline reminders auto-skip when role system prompt exists. For long threads run `compact_thread.sh <slug> --keep 6`.
- **Reviewer JSON verdict**: extracted automatically as `history/<actor>/<ts>/verdict.json`.
- **Tool whitelisting (claude)**: `--allowed-tools` fully replaces both allowlist and disallowlist.
- **Goal bridge (codex only)**: executor turns inject a `/goal bridge` addendum that hooks into codex's `get_goal`/`create_goal`/`update_goal` tools. Claude Code does not have goal tools — the bridge is codex-exclusive.

## Known sharp edges

1. **codex `-o last.md` doesn't always flush.** Auto-salvaged from `trace.jsonl`.
2. **Exit 0 ≠ task succeeded.** Always read `last.md`.
3. **`claude-opus`/`claude-sonnet` aliases ≠ Anthropic.** They route to DeepSeek-V4-Pro via Anthropic-compat endpoint.
4. **Cursor `Task` latency is unbounded.** Pool throttling can queue 10+ min. Prefer CLI when wallclock matters.
5. **Addendum/body files must be under workspace root**, not `/tmp/` (Cursor's subprocess `/tmp` is isolated).

## Quick reference

```bash
SKILL=~/.cursor/skills/agent-roundtable
$SKILL/scripts/new_thread.sh serve-review-audit "Find concurrency bugs in serve_review.py"
# edit GOAL.md, then dispatch (run directly — no nohup, no &):
$SKILL/scripts/route.sh --role planner   # see preference list
$SKILL/scripts/claude_turn.sh serve-review-audit --role planner --model opus --effort high \
  --addendum "Output artifacts/plan.md proposing concrete fixes; do not edit source."
# → wait for ROUNDTABLE_DONE: (block_until_ms: 1800000 in Shell tool, or AwaitShell)
$SKILL/scripts/codex_turn.sh  serve-review-audit --role executor --effort high \
  --addendum "Implement the plan; run pytest tests/eval/."
$SKILL/scripts/claude_turn.sh serve-review-audit --role reviewer --model opus --effort high --bare \
  --addendum "Review the executor turn against GOAL.md acceptance criteria."
```
