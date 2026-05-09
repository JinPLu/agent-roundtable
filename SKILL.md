---
name: agent-roundtable
description: Use when dispatching tasks across two or more LLM actors (Codex CLI, Claude Code, Cursor subagents) on a shared on-disk thread, when a durable cross-actor audit trail is required, or when a planner-executor-reviewer convergence loop is needed.
disable-model-invocation: true
---

# Agent Roundtable

A file-based multi-agent substrate. Codex CLI, Claude Code, and Cursor subagents take turns on a shared on-disk thread. The chat parent **orchestrates but never executes a turn itself.**

## Sub-skills (progressive disclosure)

Read the sub-skill that matches the user's intent **before** taking any action. Each sub-skill is self-sufficient; do not re-read this router once you have picked one.

| Intent | Sub-skill |
|--------|-----------|
| Initialize / configure / set API keys / generate `AGENTS.md` | `skills/roundtable-init/SKILL.md` |
| Review code, audit security, check a PR, find bugs | `skills/roundtable-review/SKILL.md` |
| Implement a feature, refactor, run the full quality loop | `skills/roundtable-develop/SKILL.md` |

## Hard rules (apply to every sub-skill)

1. **Dispatch confirmation.** Before running ANY turn script, show the [Dispatch Confirmation](#dispatch-confirmation) block and wait for user approval. The user may bypass with an explicit "go" / "dispatch now".
2. **Context hygiene.** When a turn surfaces new architectural rules, conventions, or persistent project facts, the executor or planner MUST update `AGENTS.md` (and `CLAUDE.md` if Claude-specific) and the relevant `.planning/` files **before** handing off. Stale context poisons future turns.
3. **Independent verification.** Each agent reads source files and runs verification commands directly. `THREAD.md` is a log, not evidence. The full rule lives at `roles/_independence_rule.md` and is included in every role system prompt.
4. **Cross-vendor blind for parallel review.** Parallel reviewers must come from different actor families (e.g. one OpenAI-compat, one Anthropic-compat) and MUST use the `--blind` flag. Modal adoption sycophancy is 85% when reviewers see prior verdicts.
5. **Minimal tool disablement.** Agent CLIs run with their full tool surface (Read, Write, Bash, WebSearch, WebFetch). Reviewer roles get read-only via `--permission-mode plan`; only destructive git operations are blocked for write roles.

## Dispatch Confirmation

```
Proposed dispatch
  Thread  : <slug>
  Project : <ROUNDTABLE_PROJECT_ROOT>
  Role    : <role>
  Actor   : <actor>  →  model: <model-id>
  Effort  : <low | medium | high>
  Multi?  : <single turn | N parallel>
  Budget  : <max-rounds=N | max-turns=M | max-wallclock=Xm>  (optional; default: 3 rounds, no clock cap)

Proceed? Or adjust actor / effort / budget / go multi?
```

Sub-skills cite this block by name. Do not duplicate it elsewhere.

## Substrate at a glance

- **Scripts** (under `$SKILL/scripts/`): `codex_turn.sh`, `claude_turn.sh`, `backend.sh`, `new_thread.sh`. Auto-resolve `ROUNDTABLE_PROJECT_ROOT` from the caller's git toplevel; threads land at `$PROJECT_ROOT/.roundtable/threads/<slug>/`.
- **Roles** (under `$SKILL/roles/`): `planner`, `executor`, `reviewer`, `devils-advocate`, `reviewer-aggregator`, `discussant`. Each ships a system prompt and (for reviewers) a JSON schema.
- **Models** (`$SKILL/models.json`, gitignored): user's local registry; populated via `backend.sh init`. Sub-skill `roundtable-init` walks the user through this.

Deeper reference: `docs/advanced.md`, `docs/MODEL-CAPABILITY-GUIDE.md`.
