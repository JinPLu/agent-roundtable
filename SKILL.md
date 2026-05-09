---
name: agent-roundtable
description: Multi-agent collaboration substrate for working with the user, Cursor (chat parent), Codex CLI, and Claude Code as peers around a shared on-disk thread. The user's models live in `models.json` (gitignored, chmod 600) — they edit it directly to add their endpoints; the agent reads only the non-secret metadata, WebSearches the user's models for benchmarks/pricing, fills those into `models.json`, and runs `scripts/backend.sh apply` to write the per-actor env files. The api_key never enters chat or the agent's context.
disable-model-invocation: true
---

# Agent Roundtable

A thin file-based substrate where participants take turns around a shared on-disk thread under `$ROUNDTABLE_ROOT/threads/<slug>/`. Use when two+ CLIs work on one goal or you need a durable on-disk audit trail.

## First-run setup (default flow when this skill is invoked)

> **The chat parent MUST run this wizard the first time the skill is invoked in a workspace** — i.e. whenever `scripts/backend.sh show` reports both actors as "not configured" and the user has not already arranged auth out-of-band. Skip only if the user explicitly says they have working `codex login` / `claude auth login`.

The wizard is **single-file**: everything (catalog + endpoints + active selection) lives in `<SKILL_DIR>/models.json` (gitignored, chmod 600). The user owns that file; the agent reads only the non-secret parts (model ids, providers, base URLs, capability metadata) and never reads or echoes `endpoint.api_key`.

Step-by-step (the agent runs every step except #2):

1. **Probe + initialise**: run `scripts/backend.sh show`. If `models.json` doesn't exist or `active.{codex,claude}` are both null, run `scripts/backend.sh init` to seed `<SKILL_DIR>/models.json` from `models.example.json` (chmod 600). The example ships a catalog of model entries (gpt-5.5, claude-opus, …) — most users will replace or extend it; that's expected.

2. **User edits `models.json`**: tell the user to open `<SKILL_DIR>/models.json` and:
   - Either pick an existing catalog entry that matches a model they have, or add a new one under `models.<id>`. Minimum required fields per entry: `actor` (`codex` or `claude`), `cli_arg` (the model id the CLI sends), and `endpoint: { base_url, api_key }`.
   - Set `active.codex` and/or `active.claude` to the chosen model ids. Leave either null to skip that actor (its CLI then falls back to its own login).
   - Save and reply with anything (`done`, `go`, etc.).

3. **Inspect (non-secret)**: `scripts/backend.sh show` — reports per actor: `active.{actor}=<model id>`, `cli_arg`, and a status (`ready` / `base_url only` / `api_key only` / `no endpoint block`). The api_key is never printed; only its presence is. The agent uses this output to decide which models to research.

4. **Research capabilities**: call `WebSearch` with each active model id + provider (e.g. `"deepseek-v4-pro context window benchmark pricing 2026"`). Extract: `context_window_k`, `max_output_k`, `benchmarks` (SWE-Bench Verified, Terminal-Bench, etc.), `pricing` (per-1M input/output), `best_for` tags, `underlying` (human-readable description). If WebSearch returns nothing reliable, ask the user for a docs URL and `WebFetch` it. Patch those fields directly into the matching `models.<id>` entry in `models.json` (preserve `endpoint`, `actor`, `cli_arg`). Also append the model id to whichever `role_defaults` lists make sense (`executor` and `reviewer` for top-tier, `compactor`/`triage` for cheap models).

5. **Apply**: `scripts/backend.sh apply` — reads `models.json`, walks `active.{codex,claude}`, and writes `.codex_env.local` / `.claude_env.local` (chmod 600) using each active model's `endpoint` block. Prints `APPLIED actor=… model=… base_url=…` lines so the agent has a non-secret record. The api_key is read from `models.json` by the python subprocess inside `apply` and passed to the env file via `printf %q` — it is never echoed to stdout. (For ad-hoc one-off overrides, `backend.sh codex <url> <key> <model>` and `backend.sh claude <url> <key> <model>` still work and bypass `models.json`.)

6. **Verify**: `scripts/backend.sh show` (key redacted in both `models.json` summary and `.local` dumps); then dispatch a 1-line health-check turn per active actor — e.g. `scripts/codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"`. Exit 0 with the word `ok` in `last.md` confirms the endpoint actually answers.

The flow is idempotent — re-running `init` is a no-op once `models.json` exists; re-running `apply` overwrites the `.local` files. Editing `models.json` by hand any time (new endpoints, swap active model, tweak benchmarks) and re-running `apply` is the standard switching motion. The catalog grows over time — users with more models just keep adding entries.

## Architecture — who does what

| Role | Who |
|---|---|
| **Chat parent** | The model running the IDE conversation. **Stays on the main thread; never a dispatch target.** |
| **Cursor subagent** | Any model available via Cursor's `Task` tool. |
| **Codex CLI** | Any OpenAI-compatible endpoint (OpenAI, Azure, cialloapi, local vLLM, …). Set with `scripts/backend.sh codex`. |
| **Claude CLI** | Any Anthropic-compatible endpoint (Anthropic, DeepSeek-compat, Bedrock-compat, …). Set with `scripts/backend.sh claude`. |

Any participant can play any role — planner, executor, reviewer, discussant. The chat parent decides who plays what (with `route.sh` as a hint) after confirming with the user.

## Setup

- **Env**: `ROUNDTABLE_REPO_ROOT` (auto-detected git root), `ROUNDTABLE_ROOT` (default `$ROUNDTABLE_REPO_ROOT/.roundtable`), `ROUNDTABLE_TAIL_K` (recent turns inlined; default `3`).
- **Backend (default path — single source of truth in `models.json`):**
  ```bash
  scripts/backend.sh init        # seed <SKILL_DIR>/models.json from models.example.json (gitignored, chmod 600)
  $EDITOR <SKILL_DIR>/models.json   # add `endpoint: {base_url, api_key}` to a model, set `active.{codex,claude}`
  scripts/backend.sh apply       # write .codex_env.local / .claude_env.local from the active models
  scripts/backend.sh show        # inspect current state — key never printed, only presence
  scripts/backend.sh clear codex # remove .codex_env.local → fall back to CLI's own login
  ```
- **Backend (escape-hatch, ignores `models.json`):**
  ```bash
  scripts/backend.sh codex  <base-url> <api-key> [default-model]
  scripts/backend.sh claude <base-url> <api-key> [opus-model] [sonnet-model] [haiku-model]
  ```
  Useful for ad-hoc overrides without touching `models.json`.
- **Catalog vs. registry**: `models.example.json` is the shipped catalog (tracked in git). `models.json` is the user's working copy (gitignored, holds keys). `route.sh` and `_common.sh resolve_model` read whichever exists, falling back to the example, so signal-based routing keeps working even before `init`.

## Thread layout

```
$ROUNDTABLE_ROOT/threads/<slug>/
├── THREAD.md              # five-part turn timeline (append-only)
├── THREAD_SUMMARY.md      # compacted older turns (created by compact_thread.sh)
├── GOAL.md                # goal / DoD / scope / verification commands
├── OPEN_QUESTIONS.md
├── artifacts/             # outputs from any role
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

> **CRITICAL — these rules are non-negotiable. Violating any one is a protocol failure.**

1. **Independent verification**: every agent MUST verify facts by reading actual files and running commands. Do NOT trust any other agent's summaries, self-reported outcomes, or verdicts. Evidence comes from the codebase, not from THREAD.md turn bodies. This is the single most important rule — without it, multi-agent review degenerates into rubber-stamping.
2. **Confirm dispatch**: default is to ask the user (which agent, model, effort) before each dispatch. Skip the confirmation in convergence-loop mode and other pre-agreed workflows.
3. **Single writer per path**: no two agents write to the same file concurrently. Parallel turns require disjoint file ownership, separate worktrees, or all-but-one read-only roles.
4. **No agent recursion**: only the user and chat parent orchestrate. Codex must not invoke claude or cursor-agent; claude must not invoke codex.
5. **Self-contained prompts**: subagents see no chat history — the dispatch script injects context (THREAD.md tail + GOAL.md + role guidelines + addendum) fresh each turn.
6. **Acceptance evidence**: reviewer turns must produce the structured JSON verdict per `roles/reviewer.schema.json`. "Looks good" is not a review.
7. **Cross-vendor review**: for multi-reviewer turns prefer different actors (codex + claude + cursor-subagent). Same-actor reviewers exhibit sycophantic conformity.
8. **English on disk**: all on-disk artifacts (THREAD.md, GOAL.md, OPEN_QUESTIONS.md, addenda, artifacts/, reviewer JSON) must be in English. `build_prompt` injects this automatically. Translate Chinese GOAL.md content before dispatch (keep the original as a quoted block + gloss).

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
| `backend.sh <subcmd>` | Manage per-actor endpoints. Default flow: `init` → user edits `models.json` → `apply`. | `init`, `apply [actor]`, `show [actor]`, `clear <actor>`, `codex/claude <url> <key> <model>` |

## Role × default sandbox / permission

| Role | codex (cwd; sandbox) | claude (`--permission-mode`) | Notes |
|---|---|---|---|
| **planner** | thread-dir; workspace-write | acceptEdits | Can write `artifacts/plan.md`. Read-only w.r.t. source code. |
| **executor** | repo-root; workspace-write | acceptEdits + git-destructive disallowed | Only one executor per path at a time. |
| **reviewer** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Produces structured JSON verdict. Should not write source. |
| **reviewer-aggregator** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Merges N parallel reviewers into one canonical turn. |
| **discussant** | thread-dir; workspace-write | acceptEdits | Drafts options into `artifacts/`, adds to `OPEN_QUESTIONS.md`. |

Codex non-executor roles set `cwd=<thread-dir>` so `-s workspace-write` allows writes to `<thread-dir>/artifacts/` only; source code is read-only via `--add-dir <repo-root>`. Executor flips it (cwd=repo-root) to allow source edits.

## Known sharp edges

1. **codex `-o last.md` doesn't always flush.** Auto-salvaged from `trace.jsonl`.
2. **Exit 0 ≠ task succeeded.** Always read `last.md`.

## Quick reference

```bash
SKILL=~/.cursor/skills/agent-roundtable
$SKILL/scripts/new_thread.sh serve-review-audit "Find concurrency bugs in serve_review.py"
$SKILL/scripts/route.sh --role planner
$SKILL/scripts/claude_turn.sh serve-review-audit --role planner --model opus --effort high \
  --addendum "Output artifacts/plan.md proposing concrete fixes; do not edit source."
$SKILL/scripts/codex_turn.sh  serve-review-audit --role executor --effort high \
  --addendum "Implement the plan; run pytest tests/eval/."
$SKILL/scripts/claude_turn.sh serve-review-audit --role reviewer --model opus --effort high --bare \
  --addendum "Review the executor turn against GOAL.md acceptance criteria."
```

For advanced usage (parallel dispatch, convergence loops, signal routing, Task subagent integration), see [docs/advanced.md](docs/advanced.md).
