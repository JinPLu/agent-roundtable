---
name: agent-roundtable
description: Coordinate Codex CLI, Claude Code, and Cursor subagents as peers around a shared on-disk thread. Use when dispatching tasks to two or more LLM actors, when a durable cross-actor audit trail is required, or when a planner-executor-reviewer convergence loop is needed.
disable-model-invocation: true
---

# Agent Roundtable

A file-based multi-agent substrate: Codex CLI, Claude Code, and Cursor subagents take turns on a shared on-disk thread. The **chat parent orchestrates but never executes a turn itself.**

## Sub-Skills (Progressive Disclosure)

This is a complex skill suite. **You MUST read the appropriate sub-skill file based on the user's intent before taking any action:**

- **Setup & Configuration**: If the user asks to initialize, setup, or configure agent-roundtable, or if `models.json` is missing.
  👉 **Read**: `skills/roundtable-init/SKILL.md`

- **Code Review & Auditing**: If the user asks to review code, check a PR, audit security, or find bugs.
  👉 **Read**: `skills/roundtable-review/SKILL.md`

- **Feature Development & Refactoring**: If the user asks to implement a feature, refactor code, or run the full quality loop.
  👉 **Read**: `skills/roundtable-develop/SKILL.md`

---

## Core Principles (Applies to all sub-skills)

1. **Mandatory Confirmation**: Before running ANY dispatch script (`codex_turn.sh` or `claude_turn.sh`), you MUST show the dispatch confirmation block and wait for user approval.
   ```
   Proposed dispatch
     Thread  : <slug>
     Project : <ROUNDTABLE_PROJECT_ROOT>
     Role    : <role>
     Actor   : <actor>  →  model: <model-id>
     Effort  : <low | medium | high>
     Multi?  : <single turn | N parallel>
   
   Proceed? Or adjust actor / effort / go multi?
   ```
2. **Context Hygiene**: If a turn discovers new architectural rules, conventions, or persistent project facts, the executor/planner MUST update `AGENTS.md` (and `CLAUDE.md` if Claude-specific) and the relevant `.planning/` files before handing off. Stale context poisons future turns.
3. **Independent Verification**: Each agent reads source files and runs verification commands before consulting THREAD.md. THREAD.md is a log, not evidence.
4. **Cross-vendor Review**: Parallel reviewers must come from different actor families (e.g., one OpenAI-compat, one Anthropic-compat) and MUST use the `--blind` flag.
5. **Tool Policy — Minimal Disablement**: Agent CLIs run with their **full tool surface** (Read, Write, Bash, WebSearch, WebFetch) by default. Reviewer roles are read-only via `--permission-mode plan`.

## Roles and Scripts

- **Scripts**: `$SKILL/scripts/codex_turn.sh` and `$SKILL/scripts/claude_turn.sh`
- **Usage**: `<script> <slug> --role <role> [options]` (Options: `-m`, `--effort`, `--task`, `--blind`)
- **Roles**:
  - `planner`: Produces `artifacts/plan.md`.
  - `executor`: Implements the plan.
  - `reviewer`: Structured JSON verdict.
  - `devils-advocate`: Adversarial reviewer; always `--blind`.
  - `reviewer-aggregator`: Selects most defensible verdict.
  - `discussant`: Surfaces options into `OPEN_QUESTIONS.md`.