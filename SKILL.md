---
name: agent-roundtable
description: Coordinate Codex CLI, Claude Code, and Cursor subagents as peers around a shared on-disk thread under `<repo>/.roundtable/threads/<slug>/`. Each turn appends a five-part Read/Did/Verification/Open-questions/Hand-off entry to THREAD.md. Use when dispatching tasks to two or more LLM CLIs on a single goal, when a durable cross-actor audit trail is required, when a planner-executor-reviewer convergence loop is wanted, or when the user invokes this skill by name.
disable-model-invocation: true
---

# Agent Roundtable

A file-based substrate where Codex CLI, Claude Code, and Cursor `Task` subagents take turns around a shared on-disk thread. Each turn is durable and auditable; the chat parent orchestrates but never executes a turn itself.

## Quick start

```bash
# If models.json already configured:
SKILL=~/.cursor/skills/agent-roundtable
$SKILL/scripts/new_thread.sh <slug> "<goal>"
$SKILL/scripts/route.sh --role executor    # get model suggestions
$SKILL/scripts/claude_turn.sh <slug> --role executor --effort high
```

If starting fresh, follow **First-run setup** below.

## Architecture

| Participant | Role |
|---|---|
| **Chat parent** | Orchestrates only — **never a dispatch target.** |
| **Cursor subagent** | Any model reachable via Cursor's `Task` tool. Auth via Cursor IDE. |
| **Codex CLI** | Any OpenAI-compatible endpoint (OpenAI, Azure, proxies, local vLLM, …). |
| **Claude CLI** | Any Anthropic-compatible endpoint (Anthropic, DeepSeek-compat, Bedrock-compat, …). |

Any participant can play any role — planner, executor, reviewer, discussant. The chat parent picks who plays what (with `route.sh` as a hint) after confirming with the user.

## First-run setup

> The chat parent **MUST** run this flow whenever `scripts/backend.sh show` reports both actors as ❌ NOT IMPORTED and the user has not arranged auth out-of-band. Skip only if the user confirms they have working `codex login` / `claude auth login`.
>
> Contract: **the user fills 4 fields per model; the agent fills the rest.** Everything lives in `<SKILL_DIR>/models.json` (gitignored, chmod 600). The api_key never enters chat or agent context.

1. **Init** (agent): `scripts/backend.sh init && scripts/backend.sh show`. Copies `models.example.json` → `models.json` (idempotent, chmod 600).

2. **User fills 4 fields per model** (user): open `<SKILL_DIR>/models.json`, edit a BYOK template or add a fresh entry:

   ```json
   "gpt-5": {
     "actor":   "codex",
     "cli_arg": "gpt-5",
     "endpoint": { "base_url": "https://api.openai.com/v1", "api_key": "sk-..." }
   }
   ```

   `actor` is `codex` (OpenAI-compat) or `claude` (Anthropic-compat). For `claude` shims also set `endpoint.{opus,sonnet,haiku}_model` and optionally `endpoint.claude_effort_level`. Set `active.codex` / `active.claude` to the model id. Reply `done`.

3. **Inspect** (agent): `scripts/backend.sh show` — import status (✅/❌/⚠) and catalog table (★ = active). The api_key is never printed.

4. **Research + auto-fill** (agent): for each entry lacking `underlying`, `context_window_k`, `max_output_k`, `benchmarks`, `best_for` — call `WebSearch` with model id + provider and patch values back. Follow the pricing freshness contract (Sharp edge #4). Add model id to relevant `role_defaults` lists.

5. **Apply** (agent): `scripts/backend.sh apply` writes `.codex_env.local` / `.claude_env.local` (chmod 600). The api_key is read by a python subprocess via `printf %q` — never echoed to stdout.

6. **Verify** (agent): `scripts/backend.sh show` confirms ✅ IMPORTED. Dispatch a 1-line health-check:

   ```bash
   scripts/codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"
   ```

Re-running `init` is a no-op once `models.json` exists. `apply` overwrites the `.local` files. Ad-hoc overrides: `scripts/backend.sh codex <base-url> <api-key> [model]` or `scripts/backend.sh claude <base-url> <api-key> [opus] [sonnet] [haiku] [effort]`.

## Dispatch protocol

### Model selection principles

Model selection is a judgment call, not a lookup. Apply these principles:

- **Benchmark scores are one signal.** Real task fitness depends on domain, output length, and reasoning style. `route.sh --role ROLE` prints ranked suggestions from `models.json` `role_defaults` — treat as starting points, not decisions.
- **Cross-vendor diversity reduces shared blind spots.** Anthropic-family, OpenAI-family, and Google-family have different training emphases. Prefer mixing families for reviewer fan-out.
- **Cheap companion alongside expensive dispatches.** When dispatching an expensive model (mid-tier or above), always dispatch a cheap cross-vendor companion in parallel for the same role. The companion uses `--blind`. Disagreement between the two is a quality signal — surface it to the user; do not silently discard it.
- **Default cheap for fan-out; reserve expensive for aggregation.** `codex-gpt-5` and `claude-opus` are quality-competitive with mid-tier for most executor/reviewer tasks.
- **Re-research pricing before cost-aware decisions.** Proxy endpoints change rates frequently; `models.json` pricing carries `_as_of` dates. Re-research via `WebSearch` when stale or from a proxy.

### Dispatch confirmation (mandatory before every turn)

Before dispatching **any** turn the chat parent MUST show the user this block and wait for approval:

```
Proposed dispatch
  Thread : <slug>
  Role   : <role>
  Actor  : <actor>  →  model: <model-id>  (cli_arg: <cli_arg>)
  Effort : <effort>
  Multi? : <single turn | N parallel turns: actor1 + actor2 + …>
  Est. $ : ~$<low>–<high> (input ~<Xk> tok × $<rate>/M + output est.)

Alternatives (from role_defaults):
  1. <actor1> / <model1> — <one-line capability note> — $<out>/M
  2. <actor2> / <model2> — …

Proceed with proposed? Or pick alternative / adjust effort / go multi?
```

Skip confirmation only in a pre-agreed convergence loop or explicit "dispatch now" instruction — log the skip in the addendum.

## Quality mode

When the user requests high quality or the goal is complex, run the four-phase loop:

1. **Plan** — single planner (cheapest capable). When the chosen model is mid-tier or above, dispatch a cheap cross-vendor companion in parallel using `--blind`. Optional: dispatch a reviewer on the plan as a plan-critic (different actor from planner); planner re-runs at most once.
2. **Execute** — single executor (cheapest capable). When the chosen model is mid-tier or above, dispatch a cheap cross-vendor companion in parallel using `--blind`.
3. **Review** — 2 or 3 parallel reviewers from **different** actors (never 4+). All parallel reviewers MUST use `--blind`. At least one MUST use `--role devils-advocate`. Each produces a structured JSON verdict independently.
4. **Aggregate** — high-capability model (default `cursor-claude-4.7-opus`) **selects** the most defensible verdict, merges BLOCKER/MAJOR issues from other reviewers, records dissent in `dissenting_concerns`. Never blend or average verdicts. Runs **without** `--blind`.

**Convergence stop rule:** stop the first time ALL hold: (1) ≥1 reviewer accepts with zero BLOCKER issues, and (2) ≤1 reviewer dissenting.

> **Evidence basis:** `--blind` requirement derived from sycophantic-conformity rate in parallel review without isolation. `--role devils-advocate` requirement derived from adversarial-disagreement rates with vs without explicit role. Verdict selection over synthesis validated across benchmark tasks. See `docs/advanced.md` for citations, MAX_COST_USD, and MAX_WALL_MIN defaults.

## Hard rules

> **CRITICAL — these rules are non-negotiable. Violating any one is a protocol failure.**

1. **Independent verification**: every agent MUST (1) independently read the listed source files, (2) run the verification commands in `GOAL.md`, and (3) THEN consult `THREAD.md` for context. THREAD.md turn bodies are context, not evidence. Do NOT trust any other agent's summaries or verdicts.
2. **Confirm dispatch**: show the dispatch confirmation block and wait for user approval before every turn. Skip only in a pre-agreed convergence loop or explicit "dispatch now" — log the skip.
3. **Single writer per path**: no two agents write to the same file concurrently. Parallel turns require disjoint file ownership, separate worktrees, or all-but-one read-only roles.
4. **No agent recursion**: only the user and chat parent orchestrate. Codex must not invoke claude or cursor-agent; claude must not invoke codex.
5. **Self-contained prompts**: subagents see no chat history — the dispatch script injects context (THREAD.md tail + GOAL.md + role guidelines + addendum) fresh each turn.
6. **Acceptance evidence**: reviewer turns must produce the structured JSON verdict per `roles/reviewer.schema.json`. "Looks good" is not a review.
7. **Cross-vendor review**: for multi-reviewer turns prefer different actors (codex + claude + cursor-subagent). Same-actor reviewers exhibit sycophantic conformity.
8. **English on disk**: all on-disk artifacts must be in English. `build_prompt` injects this automatically. Translate Chinese GOAL.md content before dispatch (keep original as a quoted block + gloss).

## Reference

### Thread layout

```
$ROUNDTABLE_ROOT/threads/<slug>/
├── THREAD.md              # five-part turn timeline (append-only)
├── THREAD_SUMMARY.md      # compacted older turns (compact_thread.sh)
├── GOAL.md                # goal / DoD / scope / verification commands
├── OPEN_QUESTIONS.md
├── artifacts/             # outputs from any role
├── history/<actor>/<ts>/  # prompt.md, last.md, trace.jsonl, meta.json, verdict.json, .done
└── worktrees/<name>/      # optional git worktrees
```

`<repo>/.roundtable/threads/latest` → symlink to the most recent thread.

### Five-part turn body (mandatory)

Every turn appended to `THREAD.md` MUST be exactly:

```
**Read**: <files opened, abs path + line range>
**Did**: <what was done, bulleted>
**Verification**: <commands run + outcomes; reviewer role embeds the structured JSON verdict>
**Open questions**: <new ambiguities>
**Hand-off**: <accept | revise: <who> on <what> | escalate-to-user: <q>>
```

### Scripts

| Script | Purpose | Notable flags |
|---|---|---|
| `new_thread.sh <slug> "<goal>"` | Initialise thread layout + `latest` symlink. | — |
| `codex_turn.sh <slug> --role ROLE` | One `codex exec` turn. Salvages `last.md` from `trace.jsonl`. | `-m`, `--effort`, `--sandbox`, `--blind`, `--worktree`, `--addendum[-file]`, `--timeout-s` |
| `claude_turn.sh <slug> --role ROLE` | One `claude -p` turn. Auto-attaches `roles/<role>.system.md`. | `--model`, `--effort`, `--permission-mode`, `--bare`, `--blind`, `--worktree`, `--allowed-tools`, `--addendum[-file]` |
| `append_turn.sh <slug>` | Land a Cursor Task subagent's body into `THREAD.md`. | `--actor`, `--role`, `--model`, `--body-file`, `--prompt-file`, `--tokens-in/-out` |
| `compact_thread.sh <slug>` | Compact old turns into `THREAD_SUMMARY.md`. | `--keep K` (default 6), `--dry-run` |
| `route.sh --role ROLE` | Rank models by role defaults + task signals. | `--top N`, `--json`, `--cursor-subagent`, `--budget`, `--latency`, `--output-heavy`, `--blind`, `--companion MODEL`, `--diversity` |
| `backend.sh <subcmd>` | Manage per-actor endpoints. | `init`, `apply [actor]`, `show [actor]`, `clear`, `codex/claude <url> <key> <model>` |

### Role × sandbox

| Role | codex (cwd; sandbox) | claude (`--permission-mode`) | Notes |
|---|---|---|---|
| **planner** | thread-dir; workspace-write | acceptEdits | Writes `artifacts/plan.md`. Read-only w.r.t. source. |
| **executor** | repo-root; workspace-write | acceptEdits + git-destructive disallowed | Only one executor per path at a time. |
| **reviewer** | thread-dir; workspace-write | plan + `--bare` recommended | Produces structured JSON verdict. No source writes. |
| **devils-advocate** | thread-dir; workspace-write | plan + `--bare` recommended | Adversarial reviewer; always use `--blind`. |
| **reviewer-aggregator** | thread-dir; workspace-write | plan + `--bare` recommended | Selects most defensible verdict from N parallel reviewers. |
| **discussant** | thread-dir; workspace-write | acceptEdits | Drafts options into `artifacts/`, adds to `OPEN_QUESTIONS.md`. |

### Sharp edges

1. **`codex -o last.md` doesn't always flush.** Auto-salvaged from `trace.jsonl`.
2. **Exit 0 ≠ task succeeded.** Always read `last.md`.
3. **Anthropic-compat shims have wide tail latency.** DeepSeek-V4-Pro via `api.deepseek.com/anthropic` observed at 1017s on heavy reviewer prompts. Default `--timeout-s=1500`; bump to 2400 for very large turns. Symptoms: `exit_code=124`, empty `last.json` and `stderr.log`. Per-model `latency_warning` in `models.json`.
4. **Pricing snapshots go stale.** `pricing.per_1m_*` changes; every block carries `_as_of`. Re-research via `WebSearch` when stale or `endpoint.base_url` is a proxy. User can pin with `_pinned: true`.

### Env vars and catalog

**Env vars:** `ROUNDTABLE_REPO_ROOT` (auto-detected git root) · `ROUNDTABLE_ROOT` (default `$ROUNDTABLE_REPO_ROOT/.roundtable`) · `ROUNDTABLE_TAIL_K` (recent turns inlined; default `3`) · `ROUNDTABLE_TIMEOUT_S` (default `--timeout-s`; codex `1800`, claude `1500`).

**Catalog vs. registry:** `models.example.json` is the shipped catalog (tracked in git). `models.json` is the user's working copy (gitignored). `route.sh` and `_common.sh resolve_model` fall back to the example, so routing works before `init`.

**CLI env-var contract:** `.codex_env.local` → `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`. `.claude_env.local` → `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, plus `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` and `CLAUDE_CODE_{SUBAGENT_MODEL,EFFORT_LEVEL}`.
