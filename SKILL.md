---
name: agent-roundtable
description: Multi-agent collaboration substrate for working with the user, Cursor (chat parent), Codex CLI, and Claude Code as peers around a shared on-disk thread. On first invocation runs an interactive wizard (AskQuestion + WebSearch) to configure each actor's API endpoint, key, and model — then auto-populates models.json with the researched capabilities.
disable-model-invocation: true
---

# Agent Roundtable

A thin file-based substrate where participants take turns around a shared on-disk thread under `$ROUNDTABLE_ROOT/threads/<slug>/`. Use when two+ CLIs work on one goal or you need a durable on-disk audit trail.

## First-run setup (default flow when this skill is invoked)

> **The chat parent MUST run this wizard the first time the skill is invoked in a workspace** — i.e. whenever `scripts/backend.sh show` reports both actors as "not configured" and the user has not already arranged auth out-of-band. Skip only if the user explicitly says they have working `codex login` / `claude auth login`.

Step-by-step (the agent runs this, not the user):

1. **Probe**: `scripts/backend.sh show` — if both actors print "not configured", continue; otherwise show the current config and ask the user whether to keep, switch, or add the missing actor.
2. **Ask which actor** via `AskQuestion` (one question, options: `codex` / `claude` / `both` / `skip`). This is the only multi-choice ask — everything else is one bundled chat ask.
3. **Bundled chat ask** (one chat message, the user replies with all four values together — base URL, API key, and model belong to the same triple per actor):
   ```
   Please paste your config (per actor) in a single block. Treat the key as a secret —
   I will write it straight to the chmod-600 .local file via backend.sh and never echo it.

   For codex (OpenAI-compatible):
     base_url: <e.g. https://api.openai.com/v1>
     api_key:  <sk-...>
     model:    <e.g. gpt-4o>

   For claude (Anthropic-compatible):
     base_url: <e.g. https://api.anthropic.com>
     api_key:  <sk-ant-...>
     model:    <e.g. claude-opus-4-5>   # used for opus/sonnet/haiku tiers
   ```
   Common preset URLs the agent should suggest inline so the user can just confirm: OpenAI `https://api.openai.com/v1` · Anthropic `https://api.anthropic.com` · cialloapi `https://api.cialloapi.cn/v1` · DeepSeek-compat `https://api.deepseek.com/anthropic`.
4. **Research capabilities**: call `WebSearch` with the model id and provider (e.g. `"deepseek-v4-pro context window benchmark pricing 2026"`). Extract: context window (k tokens), max output (k tokens), benchmark numbers (SWE-Bench Verified, Terminal-Bench, etc.), per-1M input/output pricing, best-for tags. If web search returns nothing reliable, ask the user to paste a docs/pricing URL and `WebFetch` it.
5. **Write the env file**: `scripts/backend.sh <actor> <base-url> <api-key> <model>` (one call per actor configured).
6. **Update `models.json`**: append (or replace) an entry for the new model under `models.<id>`, populated with the researched values (`actor`, `cli_arg`, `provider`, `underlying`, `context_window_k`, `max_output_k`, `benchmarks`, `best_for`, `pricing`). Then add the model id to `role_defaults` for whichever roles it should serve (typically `executor` and `reviewer` for top-tier, `compactor`/`triage` for cheap models).
7. **Verify**: `scripts/backend.sh show` redacts the key; `python3 -c "import json; print(json.load(open('models.json'))['models']['<id>'])"` confirms the registry update; then dispatch a 1-line health-check turn (e.g. `codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"`).

The wizard is idempotent — re-running it overwrites the `.local` file and the matching `models.json` entry.

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
- **Backend** (one-shot, switches the underlying model+API for an actor — analogous to `cc-switch`):
  ```bash
  scripts/backend.sh codex  <base-url> <api-key> [default-model]
  scripts/backend.sh claude <base-url> <api-key> [opus-model] [sonnet-model] [haiku-model]
  scripts/backend.sh show              # inspect current config (key redacted)
  scripts/backend.sh clear codex       # remove override → fall back to CLI's own login
  ```
  Writes `<SKILL_DIR>/.<actor>_env.local` (chmod 600, gitignored). `{codex,claude}_turn.sh` source it before invoking the CLI. With nothing configured, the CLIs use their own auth (`codex login`, `claude auth login`).
- **Model registry**: `models.json` is a *hint* layer for `route.sh` (per-model benchmarks, pricing, role defaults). If you switch backends, edit `models.json` to match — or just pass `--model <cli-arg>` explicitly to each turn script and ignore the registry.

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
| `backend.sh <actor> ...` | Point codex / claude actor at any OpenAI / Anthropic-compatible endpoint. | `show`, `clear <actor>` |

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
