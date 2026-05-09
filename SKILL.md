---
name: agent-roundtable
description: Multi-agent collaboration substrate for working with the user, Cursor (chat parent), Codex CLI, and Claude Code as peers around a shared on-disk thread. On first invocation runs a file-based wizard (user edits one chmod-600 template, agent reads non-secret fields, WebSearches each model, writes the .local env files, shreds the template) to configure each actor's API endpoint, key, and model — then auto-populates models.json with the researched capabilities. The api_key never enters chat history or the agent's context.
disable-model-invocation: true
---

# Agent Roundtable

A thin file-based substrate where participants take turns around a shared on-disk thread under `$ROUNDTABLE_ROOT/threads/<slug>/`. Use when two+ CLIs work on one goal or you need a durable on-disk audit trail.

## First-run setup (default flow when this skill is invoked)

> **The chat parent MUST run this wizard the first time the skill is invoked in a workspace** — i.e. whenever `scripts/backend.sh show` reports both actors as "not configured" and the user has not already arranged auth out-of-band. Skip only if the user explicitly says they have working `codex login` / `claude auth login`.

The wizard is **file-based** — the user fills in a template, the agent reads only the non-secret fields, and the api_key is shredded the moment the `.local` files are written. The key never enters chat history *or* the agent's context window.

Step-by-step (the agent runs every step except #2 — the user only edits one file):

1. **Probe + initialise**: run `scripts/backend.sh show`. If both actors are "not configured", run `scripts/backend.sh wizard-init` to write `<SKILL_DIR>/wizard.in` (chmod 600, gitignored) — a template with `[codex]` and `[claude]` blocks plus a comment block of common preset URLs.
2. **User edits the file**: tell the user to open `<SKILL_DIR>/wizard.in`, fill in `base_url`, `api_key`, `model` for whichever actor(s) they want, save, and reply `done` (or any acknowledgement). Leave a block's `api_key` blank to skip that actor.
3. **Peek (non-secret)**: `scripts/backend.sh wizard-peek` — prints `actor=… base_url=… model=… api_key=<set|blank>` per block. The agent reads this output (no api_key in it) to learn which models to research.
4. **Research capabilities**: call `WebSearch` with each model id + provider (e.g. `"deepseek-v4-pro context window benchmark pricing 2026"`). Extract: context window (k tokens), max output (k tokens), benchmark numbers (SWE-Bench Verified, Terminal-Bench, etc.), per-1M input/output pricing, best-for tags. If WebSearch returns nothing reliable, ask the user for a docs/pricing URL and `WebFetch` it.
5. **Apply**: `scripts/backend.sh wizard-apply` — parses `wizard.in`, writes `.codex_env.local` and/or `.claude_env.local` via the same `backend.sh codex/claude` codepaths, prints `APPLIED actor=… base_url=… model=…` lines, then **shreds `wizard.in`**. The agent never reads `wizard.in` directly — only the apply script does, so the api_key doesn't enter the agent's context.
6. **Update `models.json`**: append (or replace) an entry for each applied model under `models.<id>`, populated with the researched values (`actor`, `cli_arg`, `provider`, `underlying`, `context_window_k`, `max_output_k`, `benchmarks`, `best_for`, `pricing`). Add the model id to `role_defaults` for whichever roles it should serve (typically `executor` and `reviewer` for top-tier, `compactor`/`triage` for cheap models).
7. **Verify**: `scripts/backend.sh show` (key redacted) + `python3 -c "import json; print(json.load(open('models.json'))['models']['<id>'])"` to confirm the registry update; then dispatch a 1-line health-check turn (e.g. `codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"`).

The wizard is idempotent — re-running `wizard-init` requires you to first `rm wizard.in`; re-running `wizard-apply` overwrites the `.local` files. Editing `models.json` by hand for benchmark/pricing tweaks is fine and survives re-runs.

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
| `backend.sh <actor> ...` | Point codex / claude actor at any OpenAI / Anthropic-compatible endpoint. | `show`, `clear <actor>`, `wizard-init`, `wizard-peek`, `wizard-apply` |

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
