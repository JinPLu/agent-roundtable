---
name: agent-roundtable
description: Coordinate Codex CLI, Claude Code, and Cursor subagents as peers around a shared on-disk thread under `<repo>/.roundtable/threads/<slug>/`. Each turn appends a five-part Read/Did/Verification/Open-questions/Hand-off entry to THREAD.md. Use when dispatching tasks to two or more LLM CLIs on a single goal, when a durable cross-actor audit trail is required, when a planner-executor-reviewer convergence loop is wanted, or when the user invokes this skill by name.
disable-model-invocation: true
---

# Agent Roundtable

A file-based substrate where Codex CLI, Claude Code, and Cursor `Task` subagents take turns around a shared on-disk thread. Each turn is durable and auditable; the chat parent (the IDE model) orchestrates but never executes a turn itself.

## Architecture

| Participant | Role |
|---|---|
| **Chat parent** | The model running the IDE conversation. Orchestrates only — **never a dispatch target.** |
| **Cursor subagent** | Any model reachable via Cursor's `Task` tool. Auth handled by Cursor IDE. |
| **Codex CLI** | Any OpenAI-compatible endpoint (OpenAI, Azure, proxies, local vLLM, …). |
| **Claude CLI** | Any Anthropic-compatible endpoint (Anthropic, DeepSeek-compat, Bedrock-compat, …). |

Any participant can play any role — planner, executor, reviewer, discussant. The chat parent picks who plays what (with `route.sh` as a hint) after confirming with the user.

## First-run setup

> The chat parent **MUST** run this flow whenever `scripts/backend.sh show` reports both actors as ❌ NOT IMPORTED and the user has not arranged auth out-of-band. Skip only if the user confirms they have working `codex login` / `claude auth login`.
>
> Contract: **the user fills 4 fields per model; the agent fills the rest.** Everything lives in `<SKILL_DIR>/models.json` (gitignored, chmod 600). The api_key never enters chat or agent context.

Step-by-step:

1. **Init** (agent): `scripts/backend.sh init && scripts/backend.sh show`. `init` copies `models.example.json` → `models.json` (idempotent, chmod 600). The example ships one `_template` placeholder, four pre-filled `cursor-subagent` entries (no endpoint required), and four pre-researched BYOK templates (gpt-5.5, gpt-5.3-codex, claude-4.7-opus, claude-4.6-sonnet).

2. **User fills 4 fields per model** (user, in editor): open `<SKILL_DIR>/models.json` and for each model with credentials, either edit a pre-researched BYOK template or add a fresh entry under `models` with the four fields below (real JSON, no comments — the inline annotations here are for reading only):

   ```json
   "gpt-5": {
     "actor":   "codex",
     "cli_arg": "gpt-5",
     "endpoint": {
       "base_url": "https://api.openai.com/v1",
       "api_key":  "sk-..."
     }
   }
   ```

   Field semantics: any model id (must NOT start with `_`) → `actor` is `codex` (OpenAI-compat) or `claude` (Anthropic-compat) → `cli_arg` is the exact id the API expects → `endpoint.base_url` and `endpoint.api_key`. For `claude` on an Anthropic-compat shim also set `endpoint.{opus,sonnet,haiku}_model` and optionally `endpoint.claude_effort_level`. Then set `active.codex` / `active.claude` to the model id. Save, reply `done`.

3. **Inspect** (agent): `scripts/backend.sh show` — two-section summary. Per-actor import status (✅ IMPORTED / ❌ NOT IMPORTED / ⚠ PLACEHOLDER / ⚠ INCOMPLETE) and a catalog table marking active rows with ★. The api_key is never printed; only its presence.

4. **Research + auto-fill metadata** (agent): for each entry the user just added that lacks capability fields (`underlying`, `context_window_k`, `max_output_k`, `benchmarks`, `best_for`), call `WebSearch` with the model id + provider — e.g. `"gpt-5 OpenAI context window benchmark 2026"` — and patch the values back. Preserve `actor`, `cli_arg`, `endpoint`. For `pricing`, follow the freshness contract (see Sharp edges #4): re-research when `pricing._as_of` is missing/stale or `endpoint.base_url` is a discount proxy. Add the model id to relevant `role_defaults` lists.

5. **Apply** (agent): `scripts/backend.sh apply` reads `models.json`, walks `active.{codex,claude}`, writes `.codex_env.local` / `.claude_env.local` (chmod 600). The api_key is read by a python subprocess and written via `printf %q` — never echoed to stdout. Entries whose key starts with `_` or whose values contain `REPLACE_WITH:*` are skipped automatically.

6. **Verify** (agent): `scripts/backend.sh show` confirms ✅ IMPORTED. Then dispatch a 1-line health-check per active actor:

   ```bash
   scripts/codex_turn.sh _health --role discussant --addendum "Reply with the single word: ok"
   ```

   Exit 0 + `ok` in `last.md` confirms the endpoint answers.

Re-running `init` is a no-op once `models.json` exists. Re-running `apply` overwrites the `.local` files. The standard switching motion is: edit `models.json` → run `apply`. For ad-hoc overrides without touching the registry:

```bash
scripts/backend.sh codex  <base-url> <api-key> [default-model]
scripts/backend.sh claude <base-url> <api-key> [opus-model] [sonnet-model] [haiku-model] [effort]
```

## Reference

- **Env vars**: `ROUNDTABLE_REPO_ROOT` (auto-detected git root), `ROUNDTABLE_ROOT` (default `$ROUNDTABLE_REPO_ROOT/.roundtable`), `ROUNDTABLE_TAIL_K` (recent turns inlined into prompts; default `3`), `ROUNDTABLE_TIMEOUT_S` (default for `--timeout-s`; codex `1800`, claude `1500`).
- **Catalog vs. registry**: `models.example.json` is the shipped catalog (tracked in git). `models.json` is the user's working copy (gitignored, holds keys). `route.sh` and `_common.sh resolve_model` read whichever exists, falling back to the example, so signal-based routing works even before `init`.
- **CLI env-var contract** (what `backend.sh apply` writes, matching official CLI docs):
  - `.codex_env.local` → `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`. Codex CLI honors these for any OpenAI-compatible endpoint; model is also overridable via `--model` or `-c model='"…"'`. See [developers.openai.com/codex/config-reference](https://developers.openai.com/codex/config-reference).
  - `.claude_env.local` → `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, plus `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` and `CLAUDE_CODE_{SUBAGENT_MODEL,EFFORT_LEVEL}` when the registry sets them. Claude Code CLI maps each alias (`claude --model opus|sonnet|haiku`) to the corresponding default — one shim endpoint can serve all three. See [code.claude.com/docs/en/env-vars](https://code.claude.com/docs/en/env-vars).

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

## Model tiers and dispatch confirmation

### Cost tiers (as configured in `models.json`)

| Tier | Models | Approx cost (out/1M) | Suitable for |
|---|---|---|---|
| **Cheap** | `codex-gpt-5` (gpt-5.5 via proxy), `claude-opus` (DeepSeek-V4-Pro), `cursor-composer-2` | $0.4–2.5 | bulk executor/reviewer fan-out, triage, compaction |
| **Mid** | `cursor-claude-4.6-sonnet`, `cursor-gemini-3.1-pro` | $12–15 | cross-vendor review, scientific QA, diverse opinion |
| **Expensive** | `cursor-claude-4.7-opus` | $25 | final reviewer-aggregation, highest-stakes SWE-Pro tasks only |

Key fact: `claude-opus` (DeepSeek-V4-Pro, SWE-bench 80.6) and `codex-gpt-5` (GPT-5.5, Terminal-Bench 82.7) are quality-competitive with Sonnet-tier models at ~10–70× lower cost. Default to cheap-tier for all fan-out; reserve expensive-tier for aggregation.

### Dispatch confirmation protocol (mandatory before every turn)

Before dispatching **any** turn the chat parent MUST show the user this block and wait for approval or correction:

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

Skip confirmation only in a pre-agreed convergence loop (user said "keep going until reviewer accepts") or when the user explicitly says "dispatch now". Log every skipped confirmation as a note in the turn addendum.

### Multi-agent quality mode

When the user requests high quality or the goal is complex:

1. **Plan phase** — single planner (`codex-gpt-5` default, cheapest capable).
   Optional: dispatch a `reviewer` on the plan artifact as a plan-critic (different actor
   from planner); planner re-runs at most once.
2. **Execute phase** — single executor (cheapest capable; `codex-gpt-5` default).
3. **Review phase** — **2 or 3** parallel reviewers from **different** actors (e.g.
   `codex-gpt-5` + `claude-opus` + `cursor-gemini-3.1-pro`); never 4+. All parallel
   reviewer turns MUST use `--blind` (prevents modal adoption sycophancy — 85.5% rate
   without this guard, per arXiv 2605.00914). At least one reviewer MUST use
   `--role devils-advocate` (explicit adversarial role yields 99.2% vs 48.3% disagreement
   rate, per arXiv 2405.09935 / OpenReview mxBmj5LYU2). Each produces a structured JSON
   verdict independently.
4. **Aggregate phase** — `cursor-claude-4.7-opus` (expensive) **selects** the most
   defensible reviewer verdict, merges BLOCKER/MAJOR issues from other reviewers, and
   records dissent in `dissenting_concerns`. Do **not** synthesise/blend verdicts —
   selection beats synthesis in 42/42 benchmark tasks (arXiv 2603.20324). The aggregator
   runs *without* `--blind` (it must see all verdicts).

#### Expensive model + cheap companion pairs (Principle A)

Every expensive dispatch MUST spawn a cheap cross-vendor companion in parallel (not
sequential). If cheap+expensive agree → high confidence. If they disagree → escalate
disagreement to user as an explicit signal (vendor-local blind spot or ambiguity).

| Expensive dispatch | Cheap companion | Notes |
|---|---|---|
| `cursor-claude-4.7-opus` (aggregator) | `codex-gpt-5` | companion runs --blind |
| `cursor-claude-4.6-sonnet` (executor) | `claude-opus` | companion uses same role |
| `cursor-gemini-3.1-pro` (reviewer) | `codex-gpt-5` | companion uses --blind |

#### Convergence stop rule (P2 / L14 stability threshold)

Stop the review loop the **first** time ALL hold:
1. ≥ 1 reviewer returned `COVERED` on every acceptance criterion.
2. `blocking_issues` contains zero `BLOCKER` entries (MAJOR/MINOR ok).
3. Disagreement score ≤ threshold (default: ≤ 1 reviewer dissenting out of N).

Hard escape (any one stops the loop and escalates to user):
- 2 consecutive `stalled` `convergence_status` from the same reviewer.
- Any `regressed` (new failure family introduced vs prior round).
- Aggregate cost > MAX_COST_USD (default $5 per thread).
- Wallclock > MAX_WALL_MIN (default 30).

Parallel review of 3 cheap agents (~$0.07–0.87/M) costs roughly the same as a single
`cursor-claude-4.7-opus` turn at ~$25/M — but delivers cross-vendor diversity.

## Hard rules

> **CRITICAL — these rules are non-negotiable. Violating any one is a protocol failure.**

1. **Independent verification** (Principle B): every agent MUST (1) independently read the listed source files, (2) run the verification commands listed in `GOAL.md`, and (3) THEN consult `THREAD.md` for context. THREAD.md turn bodies are context, not evidence. Do NOT trust any other agent's summaries, self-reported outcomes, or verdicts. Cross-vendor agents share systemic blind spots when relying on upstream summaries (modal adoption sycophancy, 85.5% per arXiv 2605.00914) — independent ground-truth reads break the chain.
2. **Confirm dispatch**: show the dispatch confirmation block above and wait for user approval before every turn. Skip only in a pre-agreed convergence loop or explicit "dispatch now" instruction — log the skip in the addendum.
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
| `codex_turn.sh <slug> --role ROLE` | One `codex exec` turn. Salvages `last.md` from `trace.jsonl` if codex doesn't flush. | `-m`, `--effort`, `--sandbox`, `--blind`, `--worktree`, `--addendum[-file]`, `--timeout-s` |
| `claude_turn.sh <slug> --role ROLE` | One `claude -p` turn. Auto-attaches `roles/<role>.system.md` via `--append-system-prompt`. | `--model`, `--effort`, `--permission-mode`, `--bare`, `--blind`, `--worktree`, `--allowed-tools`, `--addendum[-file]` |
| `append_turn.sh <slug>` | Land a Cursor Task subagent's body into `THREAD.md`. | `--actor cursor-subagent`, `--role`, `--model`, `--body-file`, `--prompt-file`, `--tokens-in/-out` |
| `compact_thread.sh <slug>` | Compact old turns into `THREAD_SUMMARY.md`; keep last K turns in `THREAD.md`. | `--keep K` (default 6), `--dry-run` |
| `route.sh --role ROLE` | Signal-based routing: rank models by role defaults + task signals. | `--top N`, `--json`, `--cursor-subagent`, `--budget`, `--latency`, `--output-heavy`, `--blind`, `--companion MODEL`, `--diversity` |
| `backend.sh <subcmd>` | Manage per-actor endpoints. Default flow: `init` → user edits `models.json` → `apply`. | `init`, `apply [actor]`, `show [actor]`, `clear <actor>`, `codex/claude <url> <key> <model>` |

## Role × default sandbox / permission

| Role | codex (cwd; sandbox) | claude (`--permission-mode`) | Notes |
|---|---|---|---|
| **planner** | thread-dir; workspace-write | acceptEdits | Can write `artifacts/plan.md`. Read-only w.r.t. source code. |
| **executor** | repo-root; workspace-write | acceptEdits + git-destructive disallowed | Only one executor per path at a time. |
| **reviewer** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Produces structured JSON verdict. Should not write source. |
| **devils-advocate** | thread-dir; workspace-write | plan + DA system + `--bare` recommended | Adversarial reviewer; always use `--blind`. |
| **reviewer-aggregator** | thread-dir; workspace-write | plan + reviewer system + `--bare` recommended | Merges N parallel reviewers into one canonical turn. |
| **discussant** | thread-dir; workspace-write | acceptEdits | Drafts options into `artifacts/`, adds to `OPEN_QUESTIONS.md`. |

Codex non-executor roles set `cwd=<thread-dir>` so `-s workspace-write` allows writes to `<thread-dir>/artifacts/` only; source code is read-only via `--add-dir <repo-root>`. Executor flips it (cwd=repo-root) to allow source edits.

## Known sharp edges

1. **codex `-o last.md` doesn't always flush.** Auto-salvaged from `trace.jsonl`.
2. **Exit 0 ≠ task succeeded.** Always read `last.md`.
3. **Anthropic-compat shims have wide tail latency.** DeepSeek-V4-Pro via `api.deepseek.com/anthropic` has been observed at 1017s on heavy reviewer prompts. `claude_turn.sh` defaults `--timeout-s=1500` to cover this; bump to 2400 for very large turns. Symptoms of timeout: `meta.json` shows `exit_code=124`, `last.json` and `stderr.log` are empty. Wrappers may surface this as "execution backend unavailable" — re-check with a 1-line probe (`curl … /v1/messages`) before declaring the endpoint dead. Per-model `latency_warning` strings in `models.json` capture known offenders.
4. **Pricing snapshots go stale.** Capability fields (context window, benchmarks, cli_arg) are stable post-release; `pricing.per_1m_*` is not. Every shipped `pricing` block carries `_as_of`. Before any cost-aware routing decision, the chat parent re-researches via WebSearch (or asks the user) when `_as_of` is missing/stale or `endpoint.base_url` is a discount proxy. User can pin a price with `_pinned: true` to opt out of auto-refresh. See `models.example.json._readme`.

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
