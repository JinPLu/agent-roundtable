---
name: agent-roundtable
description: Coordinate Codex CLI, Claude Code, and Cursor subagents as peers around a shared on-disk thread. Each turn appends a five-part Read/Did/Verification/Open-questions/Hand-off entry to THREAD.md. Use when dispatching tasks to two or more LLM actors on a single goal, when a durable cross-actor audit trail is required, or when a planner-executor-reviewer convergence loop is needed.
disable-model-invocation: true
---

# Agent Roundtable

A file-based multi-agent substrate: Codex CLI, Claude Code, and Cursor subagents take turns on a shared on-disk thread. The **chat parent orchestrates but never executes a turn itself.**

---

## Quick start

```bash
SKILL=~/.cursor/skills/agent-roundtable
$SKILL/scripts/new_thread.sh <slug> "<one-line goal>"   # create thread
$SKILL/scripts/route.sh --role executor                  # see model suggestions
$SKILL/scripts/codex_turn.sh <slug> --role executor -m gpt-5.5
```

If models are not yet configured, see **Setup** below.

---

## Setup (first time only)

The agent fills everything except 4 fields per model. API keys never enter chat.

```bash
scripts/backend.sh init   # copies models.example.json → models.json (chmod 600)
scripts/backend.sh show   # shows import status
```

Open `<SKILL_DIR>/models.json`. For each model you want to use, fill:

```json
"my-model": {
  "actor":   "codex",           // "codex" (OpenAI-compat) or "claude" (Anthropic-compat)
  "cli_arg": "gpt-5.5",         // model name passed to CLI
  "endpoint": {
    "base_url": "https://api.openai.com/v1",
    "api_key":  "sk-..."
  }
}
```

Set `active.codex` / `active.claude` to the chosen model id. Reply **done**.

The agent then runs `backend.sh apply` (writes `.codex_env.local` / `.claude_env.local`, chmod 600) and verifies with `backend.sh show`. See `models.example.json` for BYOK templates and `docs/MODEL-CAPABILITY-GUIDE.md` for actor capabilities.

---

## Before every dispatch — mandatory confirmation

The chat parent MUST show this block and wait for user approval before dispatching any turn:

```
Proposed dispatch
  Thread  : <slug>
  Project : <ROUNDTABLE_PROJECT_ROOT, or "none — tell me the path if agents need project files">
  Role    : <role>
  Actor   : <actor>  →  model: <model-id>  (cli_arg: <cli_arg>)
  Effort  : <low | medium | high>
  Multi?  : <single turn | N parallel: actor1 + actor2 + …>
  Est. $  : ~$<low>–<high>

Alternatives:
  1. <actor> / <model> — <why> — $<out>/M out
  2. …

Proceed? Or adjust actor / effort / go multi?
```

**Project root**: `ROUNDTABLE_PROJECT_ROOT` is the single source of truth — agents are mounted on it (full repo read/write within sandbox), threads live at `$PROJECT_ROOT/.roundtable/threads/<slug>/`, and `.planning/` index files (if present) are listed in every prompt. Auto-detected as the caller's `git rev-parse --show-toplevel`; override only when running from outside the project.

Skip confirmation only in a pre-agreed convergence loop or explicit "dispatch now" — log the skip in the addendum.

---

## Roles and actors

| Role | What it does | Typical actor |
|------|-------------|---------------|
| **planner** | Produces `artifacts/plan.md` | cheapest capable |
| **executor** | Implements the plan | cheapest capable |
| **reviewer** | Structured JSON verdict | different actor from executor |
| **devils-advocate** | Adversarial reviewer; always `--blind` | any; cheap |
| **reviewer-aggregator** | Selects most defensible verdict | high-capability |
| **discussant** | Surfaces options into `OPEN_QUESTIONS.md` | any |

**Model selection principles:**
- `route.sh --role ROLE` prints ranked suggestions — treat as starting points, not decisions.
- Mix vendor families for fan-out (OpenAI / Anthropic / Google have different blind spots).
- When dispatching a mid-tier or expensive model, always dispatch a cheap cross-vendor companion in parallel with `--blind`. Disagreement is a quality signal — surface it.
- Default cheap for fan-out; reserve expensive models for aggregation.
- Pricing in `models.json` carries `_as_of` dates — re-search before cost-sensitive decisions.

---

## Quality mode

For complex goals, run this four-phase loop:

1. **Plan** — cheapest capable planner. If mid-tier+, add cheap `--blind` companion.
2. **Execute** — cheapest capable executor. If mid-tier+, add cheap `--blind` companion.
3. **Review** — 2–3 parallel reviewers from **different** actors, all `--blind`, at least one `--role devils-advocate`.
4. **Aggregate** — high-capability model (e.g. `cursor-claude-4.7-opus`) **selects** the most defensible verdict; merges BLOCKERs; records dissent. Runs **without** `--blind`.

**Stop** when: ≥1 reviewer accepts with zero BLOCKERs AND ≤1 reviewer dissenting.

---

## Tool policy — minimal disablement

Agent CLIs run with their **full tool surface** (Read, Write, Bash, WebSearch, WebFetch, …) by default. Restrictions are only applied when necessary:

- **Reviewer / aggregator / devils-advocate**: write protection comes from `--permission-mode plan`. No tool allowlist — diagnostic tools (WebSearch, WebFetch, Bash) stay available.
- **Executor / planner / discussant**: only destructive git operations are blocked (`push`, `rebase`, `reset --hard`, `fetch`, `remote`, `config`).
- **Web search**: Claude Code's native `WebSearch` / `WebFetch` are enabled out of the box. Codex CLI's `browser_use` and `in_app_browser` features are stable+enabled; for explicit search add an MCP server (`codex mcp add ddg -- uvx duckduckgo-mcp-server` or similar).

## Hard rules

> Violating any rule is a protocol failure.

1. **Independent verification**: each agent reads source files and runs verification commands before consulting THREAD.md. THREAD.md is a log, not evidence.
2. **Confirm before dispatch**: show the confirmation block; wait for approval.
3. **Single writer per path**: parallel turns need disjoint file ownership or read-only roles.
4. **No agent recursion**: only the user and chat parent orchestrate. Agents must not invoke other agents.
5. **Self-contained prompts**: each turn script injects context fresh (THREAD.md tail + GOAL.md + role guidelines + addendum). Agents see no chat history.
6. **Structured verdict**: reviewer turns produce JSON per [`roles/reviewer.schema.json`](roles/reviewer.schema.json). "Looks good" is not a review.
7. **Cross-vendor review**: parallel reviewers must come from different actor families.
8. **English on disk**: all artifacts in English.

---

## Reference

### Thread layout

```
$ROUNDTABLE_ROOT/threads/<slug>/
├── GOAL.md                      # goal, DoD, scope, verification commands
├── THREAD.md                    # append-only five-part turn log
├── THREAD_SUMMARY.md            # compacted history (compact_thread.sh)
├── OPEN_QUESTIONS.md
├── artifacts/                   # outputs from any role
├── history/<actor>/<ts>/        # prompt.md, last.md, trace.jsonl, meta.json, verdict.json
└── worktrees/<name>/            # optional git worktrees
```

### Five-part turn body (mandatory format)

```
**Read**: <files opened — abs path + line range>
**Did**: <what was done, bulleted>
**Verification**: <commands + outcomes; reviewer JSON verdict goes here>
**Open questions**: <new ambiguities>
**Hand-off**: <accept | revise: <who> on <what> | escalate-to-user: <q>>
```

### Key scripts

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `new_thread.sh <slug> "<goal>"` | Create thread + `latest` symlink | — |
| `codex_turn.sh <slug> --role ROLE` | One `codex exec` turn | `-m`, `--effort`, `--task[-file]`, `--blind` |
| `claude_turn.sh <slug> --role ROLE` | One `claude -p` turn | `-m`, `--effort`, `--task[-file]`, `--blind` |
| `append_turn.sh <slug>` | Land Cursor subagent output into THREAD.md | `--actor`, `--role`, `--model`, `--body-file` |
| `compact_thread.sh <slug>` | Compact old turns into THREAD_SUMMARY.md | `--keep K` (default 6) |
| `route.sh --role ROLE` | Rank models by role defaults + signals | `--top N`, `--json`, `--budget`, `--latency`, `--diversity` |
| `backend.sh <subcmd>` | Manage per-actor endpoints | `init`, `apply`, `show`, `clear`, `codex/claude <url> <key>` |

### Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `ROUNDTABLE_PROJECT_ROOT` | auto (caller's `git rev-parse --show-toplevel`) | The user's project repo. Threads live in `$PROJECT_ROOT/.roundtable/`; agents mount this as cwd or `--add-dir`. |
| `ROUNDTABLE_ROOT` | `$PROJECT_ROOT/.roundtable` | Threads root override (rarely needed). |
| `ROUNDTABLE_REPO_ROOT` | (alias of `PROJECT_ROOT`) | Deprecated; legacy alias kept for backward compat. |
| `ROUNDTABLE_TAIL_K` | `3` | Recent turns inlined into prompts |
| `ROUNDTABLE_TIMEOUT_S` | codex `1800`, claude `1500` | Hard wallclock cap per turn |

For deep-dive on scripts, model capability, and known sharp edges: `docs/SCRIPTS-ANALYSIS.md`, `docs/MODEL-CAPABILITY-GUIDE.md`, `docs/advanced.md`.
