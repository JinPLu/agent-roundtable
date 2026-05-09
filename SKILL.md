---
name: agent-roundtable
description: Multi-agent collaboration substrate for working with the user, Cursor (chat parent), Codex CLI, and Claude Code as peers around a shared on-disk thread. The user's models live in `models.json` (gitignored, chmod 600) — they edit it directly to add their endpoints; the agent reads only the non-secret metadata, WebSearches the user's models for benchmarks/pricing, fills those into `models.json`, and runs `scripts/backend.sh apply` to write the per-actor env files. The api_key never enters chat or the agent's context.
disable-model-invocation: true
---

# Agent Roundtable

A thin file-based substrate where participants take turns around a shared on-disk thread under `$ROUNDTABLE_ROOT/threads/<slug>/`. Use when two+ CLIs work on one goal or you need a durable on-disk audit trail.

## First-run setup (default flow when this skill is invoked)

> **The chat parent MUST run this wizard the first time the skill is invoked in a workspace** — i.e. whenever `scripts/backend.sh show` reports both actors as ❌ NOT IMPORTED and the user has not already arranged auth out-of-band. Skip only if the user explicitly says they have working `codex login` / `claude auth login`.

The contract is **the user fills 4 fields per model; the agent fills the rest.** Everything lives in `<SKILL_DIR>/models.json` (gitignored, chmod 600).

Step-by-step:

1. **Init + show** (agent): `scripts/backend.sh init && scripts/backend.sh show`. `init` copies `models.example.json` to `models.json` (idempotent, chmod 600). The shipped example contains one `_template` placeholder under `models` plus four pre-filled `cursor-subagent` entries that need no endpoint.

2. **User fills 4 fields per model** (user, in editor): open `<SKILL_DIR>/models.json` and for each model with credentials, replace the `_template` entry (or add a new key) with:
   ```json
   "gpt-5": {                                      // ← any id you want (must NOT start with _)
     "actor":   "codex",                           // codex (OpenAI-compat) or claude (Anthropic-compat)
     "cli_arg": "gpt-5",                           // exact model id the API expects
     "endpoint": {
       "base_url": "https://api.openai.com/v1",
       "api_key":  "sk-..."
     }
   }
   ```
   For Claude on a shim (DeepSeek-compat etc.) also add `endpoint.{opus,sonnet,haiku}_model` and (optional) `endpoint.claude_effort_level`. Then set `active.codex` and/or `active.claude` to the model id. Save and reply `done`.

3. **Inspect non-secret state** (agent): `scripts/backend.sh show` prints a two-section summary — per-actor import status (✅ IMPORTED / ❌ NOT IMPORTED / ⚠ PLACEHOLDER / ⚠ INCOMPLETE) and a catalog table marking active rows with ★. The api_key is never printed; only its presence is.

4. **Research + auto-fill metadata** (agent): for each entry that the user just added (i.e. has an `endpoint` block but lacks `underlying` / `context_window_k` / `max_output_k` / `benchmarks` / `best_for` / `pricing`), call `WebSearch` with the model id + provider — e.g. `"gpt-5 OpenAI context window benchmark pricing 2026"`. Patch the discovered values back into the same `models.<id>` entry, preserving `actor`, `cli_arg`, `endpoint`. If WebSearch returns nothing reliable, ask the user for a docs URL and `WebFetch` it. Then add the model id to the appropriate `role_defaults` lists (typically `executor` + `reviewer` for top-tier, `compactor` + `triage` for cheap models).

5. **Apply** (agent): `scripts/backend.sh apply` reads `models.json`, walks `active.{codex,claude}`, and writes `.codex_env.local` / `.claude_env.local` (chmod 600). The api_key is read by a python subprocess inside `apply` and written via `printf %q` — never echoed to stdout. `apply` automatically skips any entry whose key starts with `_` or whose values still contain `REPLACE_WITH:*` placeholders.

6. **Verify** (agent): `scripts/backend.sh show` to confirm ✅ IMPORTED with the right model id, then dispatch a 1-line health-check per active actor — e.g. `scripts/codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"`. Exit 0 + `ok` in `last.md` confirms the endpoint actually answers.

Re-running `init` is a no-op once `models.json` exists. Re-running `apply` overwrites the `.local` files. Editing `models.json` by hand to add/swap/tweak entries and re-running `apply` is the standard switching motion. For ad-hoc overrides without touching the registry: `scripts/backend.sh codex <url> <key> <model>` / `scripts/backend.sh claude <url> <key> <opus> [sonnet] [haiku] [effort]` writes the `.local` file directly.

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
- **CLI env-var contract** (what `backend.sh apply` writes, matching official CLI docs):
  - `.codex_env.local` → `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`. Codex CLI honors these for any OpenAI-compatible endpoint (model also overridable via `--model` / `-c model='"…"'`). See [developers.openai.com/codex/config-reference](https://developers.openai.com/codex/config-reference).
  - `.claude_env.local` → `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, plus `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` and `CLAUDE_CODE_{SUBAGENT_MODEL,EFFORT_LEVEL}` when the registry sets them. Claude Code CLI maps each model alias (`claude --model opus|sonnet|haiku`) to the corresponding default, so a single shim endpoint can serve all three roles. See [code.claude.com/docs/en/env-vars](https://code.claude.com/docs/en/env-vars).
  - The api_key is written via a python subprocess that reads `models.json` directly and emits `printf %q`-quoted assignments — never echoed to stdout, never enters chat or the agent's context.

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
