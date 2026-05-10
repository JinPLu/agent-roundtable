---
name: agent-roundtable
description: Use when dispatching tasks to two or more LLM actors on a single goal, when comparing candidate implementations across vendors, or when running an audit-trailed planner-executor-reviewer convergence loop.
disable-model-invocation: true
---

# Agent Roundtable

A file-based multi-agent substrate. Codex CLI, Claude Code, and Cursor subagents take turns on a shared on-disk thread. The chat parent **orchestrates but never executes a turn itself.**

## Sub-skills (progressive disclosure)

Read the sub-skill that matches the user's intent **before** taking any action. Each sub-skill is self-sufficient; do not re-read this router once you have picked one. Ordered low to high commitment.

| Intent | Sub-skill |
|--------|-----------|
| Configure / set API keys / generate `AGENTS.md` for a fresh checkout | `skills/roundtable-setup/SKILL.md` |
| Open-ended design question, architecture/planning, or cross-vendor research → options then executable plan | `skills/roundtable-plan/SKILL.md` |
| Cross-vendor blind review, audit, PR check — verdict only, no code changes | `skills/roundtable-review/SKILL.md` |
| Single executor implements **`artifacts/PLAN.md`** (authoritative) + `GOAL.md`; sync external Cursor plans via `import_plan.sh` before execute | `skills/roundtable-execute/SKILL.md` |
| Orchestrated plan → execute → review loops with budget / stall / scope control | `skills/roundtable-goal/SKILL.md` |

## Hard rules (apply to every sub-skill)

1. **Evidence-grounded orchestration.** The chat parent (a) **reads on-disk evidence before recommending, dispatching, or summarising** — `models.json` entries for any actor proposed; `GOAL.md` (including **Plan source**) before discussing scope or success criteria; **`artifacts/PLAN.md`** when executing or reviewing a plan-bound thread; `THREAD.md` tail and the latest `verdict.json` for any thread in flight; the actual source files or `git diff` before recommending fixes. Research scripts (`research_cache.py`) are necessary but **not sufficient** — they confirm freshness, not content. (b) **Never produces content that should come from a turn** (reviewer verdicts, executor diffs, planner option matrices, aggregated plans). If a request fits a sub-skill's deliverable, dispatch — do not answer inline from memory or a `WebSearch` skim.

2. **Dispatch via the Confirmation block.** For every turn: (i) run `python3 scripts/print_dispatch_block.py --model <id> --role <role> [--effort <e>] [--thread <slug>]` and paste its stdout verbatim — do not hand-compose; (ii) collect approval via the `AskQuestion` in [Confirmation response](#confirmation-response). `go` is the only trigger for exporting `ROUNDTABLE_DISPATCH_CONFIRMED=1`. Headless callers may pre-export it or pass `--force`. Turn scripts refuse otherwise via `_common.sh:check_dispatch_confirmed`.

3. **Pricing-freshness cache.** Before recommending any model alias / pricing fact, run `python3 scripts/lib/research_cache.py --thread <slug>`. Exit 0 → proceed; exit 1 → run `scripts/refresh_pricing_snapshot.py` first. Memory-only pricing claims outside the cache MUST be flagged "UNVERIFIED — please confirm".

4. **Cross-vendor diversity for parallel turns.** Any N≥2 parallel turns on the same target — reviewers, planners producing an option matrix, or executor-race candidates — MUST come from different actor families. Reviewers additionally MUST use `--blind`. Modal adoption sycophancy is ~85% otherwise (arXiv 2605.00914), and same-vendor planners correlate via shared training data. `scripts/lib/check_review_diversity.py` warns at aggregator dispatch.

5. **Budget cap before each new round.** Convergence loops (`roundtable-goal`) MUST run `python3 scripts/lib/check_budget.py <thread_dir>` before starting a new round. Surface budget hit; do not silently extend.

## Mechanics (automated — no parent action required)

The following are enforced by scripts or role prompts; they are not part of the parent's checklist but are documented here so behaviour is predictable:

- **Verdict schema validation** — every reviewer turn's `verdict.json` is validated against `roles/reviewer.schema.json` by `_common.sh:extract_json_verdict`; re-verifiable via `scripts/lib/validate_verdict.py`.
- **Budget ledger** — every turn appends a cost record to `<thread_dir>/.budget_ledger.jsonl` via `_common.sh:append_budget_ledger`.
- **Tool surface per role** — turn scripts hardcode permission tiers: reviewer / planner / discussant → read-only (`--permission-mode plan` / `--sandbox read-only` / `Task(readonly:true)`); executor → `--permission-mode dontAsk` + `.claude/settings.json` deny list; others → `acceptEdits` + same deny list. See [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md).
- **Independence within a turn** — each turn's agent reads source files and runs verification commands directly (`THREAD.md` is a log, not evidence). Enforced via `roles/_independence_rule.md` injected into every role's system prompt.
- **Project-root guard** — `_common.sh` warns when `ROUNDTABLE_PROJECT_ROOT` resolves to the skill's own directory; `roundtable-setup` Phase 0 prevents this interactively.
- **Context hygiene** — when a turn surfaces a persistent project fact, the executor/planner role prompt instructs it to update `AGENTS.md` / `.planning/` before handing off. Not enforced by the parent.
- **Route disambiguation** — `models.json` aliases use a route prefix so the chat parent and the user always see which path runs: `codex-cli-*` → Codex CLI (`codex_turn.sh`), `claude-code-cli-*` → Claude Code CLI (`claude_turn.sh`), `cursor-*` → Cursor subagent (`Task(...)`). Two aliases for the same vendor model on different routes have different prices and failure modes — never collapse them in conversation.
- **Failover requires re-confirm (standalone turns)** — outside `/roundtable-goal`, if a turn script fails (HTTP 5xx, timeout, vendor-specific 502 like `claude-api.org`) and the parent considers switching route (e.g. `claude-code-cli-opus` → `cursor-claude-4.7-opus`), it MUST call `AskQuestion(retry-same-route / fallback-to-<other> / cancel)` and re-paste the Dispatch Confirmation for the new route. Silent fallback hides cost / quality changes.
- **Goal-mode autonomy override** — within an accepted `/roundtable-goal` loop, the Phase 0 Dispatch Confirmation is the **single** user touchpoint; in-loop turns (including per-reviewer fallback after 5xx) do **not** re-confirm. The loop self-corrects via cross-vendor turns. Only `check_budget.py` failure or executor `escalate-to-user` may surface back to the user. See `skills/roundtable-goal/SKILL.md` §"Autonomy contract".

## Dispatch Confirmation

```
Proposed dispatch
  Thread  : <slug>
  Project : <ROUNDTABLE_PROJECT_ROOT>
  Role    : <role>
  Alias   : <alias>  (<actor>)                    ← key in models.json
  Route   : <CLI vs Cursor subagent + base_url>   ← what actually runs
  Specs   : <Price per 1M in/out> | <Key benchmarks> | <best_for/notes>
  Effort  : <low | medium | high>
  Est.    : $<low>–$<high>/turn  via `route.sh --role <role> -m <alias> --estimate --turns 1`
  Multi?  : <single turn | N parallel>
  Budget  : <max-rounds=N | max-turns=M | max-wallclock=Xm>  (optional; default: 3 rounds, no clock cap)
```

`Alias` is the **key in `models.json`** (e.g. `claude-code-cli-opus`). `Route` is **how the turn actually runs** (Claude Code CLI vs Codex CLI vs Cursor subagent + the upstream base_url). The same underlying vendor model can ship via different routes with different prices, proxies, and failure modes — never conflate them.

### Confirmation response

After pasting the block above, the chat parent **MUST** call `AskQuestion` — do not emit a prose "shall we proceed?":

```
AskQuestion(
  prompt="按上述方案发车？",
  options=[
    {id: "go",     label: "GO"},
    {id: "adjust", label: "调整 (我来说改什么)"},
    {id: "cancel", label: "取消"},
  ],
)
```

- `go` → export `ROUNDTABLE_DISPATCH_CONFIRMED=1` and proceed.
- `adjust` → wait for the user's free-form description (e.g. "换 codex，budget 5 轮"), re-generate the block, then re-show this AskQuestion.
- `cancel` → abort.

**Headless / scripted callers** bypass this gate by exporting `ROUNDTABLE_DISPATCH_CONFIRMED=1` before calling the turn script, or by passing `--force`. The AskQuestion gate is Cursor-interactive only.

The chat parent MUST run `route.sh ... --estimate` (or `python3 scripts/lib/route.py --role <role> -m <model> --estimate`) before showing the confirmation; do not hand-estimate. The estimator and recalibration procedure (`scripts/recalibrate_token_budgets.py --since-days 30`) are documented in [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md). Sub-skills cite this block by name; do not duplicate it elsewhere.

## Substrate at a glance

**User-facing scripts** (the 5 you actually call):

| Script | Purpose |
|---|---|
| `backend.sh` | Initialise / show / update model registry + API keys |
| `new_thread.sh` | Create a new thread directory |
| `import_plan.sh` | Copy a Cursor / external plan into `artifacts/PLAN.md` and refresh `GOAL.md` **Plan source** |
| `codex_turn.sh` / `claude_turn.sh` | Dispatch one turn against a thread |

**Agent-orchestrator scripts** (the chat parent calls these per SKILL.md instructions):

| Script | Purpose |
|---|---|
| `print_dispatch_block.py` | Generate the Dispatch Confirmation block (Hard Rule #2) |
| `route.sh` (wraps `lib/route.py`) | Pick actor for a role, estimate cost |
| `lib/scope_check.py` | Verify executor diff vs GOAL.md In-scope paths |
| `lib/research_cache.py` | Per-thread pricing freshness cache (Hard Rule #3) |
| `lib/check_budget.py` | Verify thread budget cap before new round |

**Maintenance** (run occasionally): `recalibrate_token_budgets.py`, `refresh_pricing_snapshot.py`, `compact_thread.sh`.

**Internal**: `_common.sh` (sourced), `append_turn.sh` (called by turn scripts), `wait_for_done.sh` (parallel poller, advanced use), `lib/*.py` not listed above (used internally by the scripts above; do not invoke directly).

All scripts auto-resolve `ROUNDTABLE_PROJECT_ROOT` from the caller's git toplevel; threads land at `$PROJECT_ROOT/.roundtable/threads/<slug>/`.

**Roles** (under `$SKILL/roles/`): `planner`, `executor`, `executor-fast`, `reviewer`, `reviewer-aggregator`, `devils-advocate`, `discussant`, `researcher`, `researcher-deep`. Each ships a system prompt; reviewer family also ships a JSON schema.

**Models** (`$SKILL/models.json`, gitignored): user's local registry; populated via `backend.sh init`. Sub-skill `roundtable-setup` walks the user through this.

Deeper reference: `docs/advanced.md`, `docs/MODEL-CAPABILITY-GUIDE.md`.
