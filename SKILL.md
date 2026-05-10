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
| Single executor implements `artifacts/PLAN.md` / `GOAL.md`; scope check after diff | `skills/roundtable-execute/SKILL.md` |
| Orchestrated plan → execute → review loops with budget / stall / scope control | `skills/roundtable-goal/SKILL.md` |

## Hard rules (apply to every sub-skill)

1. **Research-before-recommend.** Before recommending any model alias, proxy `base_url`, `cli_arg`, or pricing fact during setup or routing, the chat parent MUST cite one of: (a) a `WebSearch` / `WebFetch` result with URL, or (b) a `models.json` entry whose `pricing._as_of` is ≤30 days old (verified via `scripts/lib/check_pricing_freshness.py`). Memory-only assertions MUST be flagged "UNVERIFIED — please confirm" before surfacing to the user.
2. **Dispatch confirmation.** Before running ANY turn script, show the [Dispatch Confirmation](#dispatch-confirmation) block and wait for user approval. The user may bypass with an explicit "go" / "dispatch now". Turn scripts call `_common.sh:check_dispatch_confirmed` which refuses unless `ROUNDTABLE_DISPATCH_CONFIRMED=1` is exported by the parent (or `--force` is passed).
3. **Context hygiene.** When a turn surfaces new architectural rules, conventions, or persistent project facts, the executor or planner MUST update `AGENTS.md` (and `CLAUDE.md` if Claude-specific) and the relevant `.planning/` files **before** handing off. Stale context poisons future turns.
4. **Independent verification.** Each agent reads source files and runs verification commands directly. `THREAD.md` is a log, not evidence. The full rule lives at `roles/_independence_rule.md` and is included in every role system prompt.
5. **Cross-vendor blind for parallel review.** Parallel reviewers must come from different actor families (e.g. one OpenAI-compat, one Anthropic-compat) and MUST use the `--blind` flag. Modal adoption sycophancy is 85% when reviewers see prior verdicts. `scripts/lib/check_review_diversity.py` warns at aggregator dispatch time when the last N reviewers came from the same family.
6. **Tool surface by role.** Three permission tiers, vendor-enforced:
   - **Reviewer / planner / discussant-style** roles → read-only: Claude `--permission-mode plan`, Codex `--sandbox read-only`, Cursor subagent `Task(readonly:true)`. Planner output captured under `artifacts/plan-<actor>-*.md`.
   - **Executor** roles → Claude `--permission-mode dontAsk` + explicit allow list in `<project_cwd>/.claude/settings.json`; Codex executor → `--sandbox workspace-write` with deny on destructive git.
   - **Other roles** → Claude `acceptEdits` + same `.claude/settings.json` deny list.
   
   Headless `claude -p` cannot answer permission prompts, so allow-list IS the contract. `<project_cwd>/.claude/settings.json` is the single source of truth (Anthropic docs: `--add-dir` paths do NOT contribute settings; cwd-anchored). `roundtable-setup` copies `templates/.claude/settings.json` into the user's project root; the skill repo also ships a sibling `.claude/settings.json` for self-audits. Full table at [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md).
7. **Model Awareness — mechanical.** The chat parent MUST invoke `python3 scripts/print_dispatch_block.py --model <id> --role <role> [--effort <e>] [--thread <slug>] [--project <path>]` and paste its stdout verbatim into the Dispatch Confirmation. The script reads `models.json` directly, delegates pricing/estimate to `route.py`, and explicitly excludes deprecated foot-gun keys (`_official_before_discount` / `_pretax_reference`). Do NOT compose the block by hand; the chat parent has misquoted pricing twice in this skill's history when allowed to "remember" the registry.
8. **Verdict and budget audit trails.** Every reviewer turn produces `verdict.json` validated against `roles/reviewer.schema.json` (automatic via `_common.sh:extract_json_verdict`; structurally re-verifiable via `scripts/lib/validate_verdict.py`). Every turn appends a cost record to `<thread_dir>/.budget_ledger.jsonl` (automatic via `_common.sh:append_budget_ledger` inside `finalize_turn`). Convergence loops MUST run `scripts/lib/check_budget.py <thread_dir>` before each new round.

## Dispatch Confirmation

```
Proposed dispatch
  Thread  : <slug>
  Project : <ROUNDTABLE_PROJECT_ROOT>
  Role    : <role>
  Actor   : <actor>  →  model: <model-id>
  Specs   : <Price per 1M in/out> | <Key benchmarks> | <best_for/notes>
  Effort  : <low | medium | high>
  Est.    : $<low>–$<high>/turn  via `route.sh --role <role> -m <model> --estimate --turns 1`
  Multi?  : <single turn | N parallel>
  Budget  : <max-rounds=N | max-turns=M | max-wallclock=Xm>  (optional; default: 3 rounds, no clock cap)

Proceed? Or adjust actor / effort / budget / go multi?
```

The chat parent MUST run `route.sh ... --estimate` (or `python3 scripts/lib/route.py --role <role> -m <model> --estimate`) before showing the confirmation; do not hand-estimate. The estimator and recalibration procedure (`scripts/recalibrate_token_budgets.py --since-days 30`) are documented in [docs/dispatch-mechanics.md](docs/dispatch-mechanics.md). Sub-skills cite this block by name; do not duplicate it elsewhere.

## Substrate at a glance

- **Scripts** (under `$SKILL/scripts/`): `codex_turn.sh`, `claude_turn.sh`, `backend.sh`, `new_thread.sh`. Auto-resolve `ROUNDTABLE_PROJECT_ROOT` from the caller's git toplevel; threads land at `$PROJECT_ROOT/.roundtable/threads/<slug>/`.
- **Roles** (under `$SKILL/roles/`): `planner`, `executor`, `executor-fast`, `reviewer`, `reviewer-aggregator`, `devils-advocate`, `discussant`, `researcher`, `researcher-deep`. Each ships a system prompt; reviewer family also ships a JSON schema.
- **Models** (`$SKILL/models.json`, gitignored): user's local registry; populated via `backend.sh init`. Sub-skill `roundtable-setup` walks the user through this.

Deeper reference: `docs/advanced.md`, `docs/MODEL-CAPABILITY-GUIDE.md`.
