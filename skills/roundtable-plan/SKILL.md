---
name: roundtable-plan
description: Use when the user wants a robust implementation plan, architecture design, step-by-step strategy, or open-ended cross-vendor research before committing to a single approach. Phase A surfaces options; Phase B aggregates into an executable PLAN.md.
disable-model-invocation: true
---

# Roundtable Plan

> The chat parent orchestrates; this sub-skill never auto-dispatches (see root [SKILL.md](../../SKILL.md)).

Use when the user wants cross-vendor perspectives before committing to code **or** when they need an option matrix and trade-offs first (the former `roundtable-discuss` flow is **Phase A only**).

## Already have a Cursor plan?

Many users draft in **Cursor Plan mode** first, then use roundtable to **review / stress-test** the plan and edit it in place. That workflow **skips Phase A and Phase B** here:

1. **Import** the canonical plan file (one command — auto-derives slug and auto-creates the thread):

   ```bash
   bash $SKILL/scripts/import_plan.sh /absolute/path/to/.cursor/plans/your.plan.md
   # → slug=<filename>-<YYYYMMDD>, GOAL.md goal-line from plan frontmatter / H1
   ```

   Re-run the same command after you edit the source file so `artifacts/PLAN.md` stays in sync. Pass `--slug <existing>` when re-importing into a slug you already have.
3. Point **`roundtable-review`** at `artifacts/PLAN.md` (or the thread’s `GOAL.md` rubric) if you want cross-vendor blind review; merge feedback into the plan, then **`import_plan.sh` again** if the source of truth was outside the thread.
4. Hand off to **`roundtable-execute`** — the executor role reads **`artifacts/PLAN.md` in full** before coding when `GOAL.md` **Plan source** is present (see `roles/executor.system.md`).

Use **Phase A / B below** only when you are **not** starting from a Cursor plan and want multi-model option discovery + `artifacts/PLAN.md` from scratch.

Planning is split into **Phase A** (research / divergence → `artifacts/options.md`) and **Phase B** (synthesis / convergence → `artifacts/PLAN.md`). The chat parent decides whether to run both phases in one session or stop for a human checkpoint after Phase A.

## Stop-after Phase A (discuss-equivalent)

**Only when the user's request does not already indicate scope**, ask:

```
AskQuestion(
  prompt="Plan 走到哪一步？",
  options=[
    {id: "phase-a", label: "只跑 Phase A — 看完 options.md 后我再决定"},
    {id: "both",    label: "一路跑到 PLAN.md"},
  ],
)
```

**Skip this question** when the user has already signalled intent — e.g. "出几个方案让我选" / "列 options" → `phase-a`; "出 PLAN" / "做计划" / "实现 X" → `both`. Set `ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a` accordingly.

The environment variable is the headless / scripted convention; the AskQuestion (when needed) is just its Cursor-interactive source of truth.

| Variable | Effect |
|----------|--------|
| `ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a` | After Phase A completes (merged `artifacts/options.md`), **do not** dispatch Phase B until the user explicitly continues. The parent surfaces `options.md` and waits for approval to proceed to aggregation. |
| unset or empty | Run Phase A then Phase B in one orchestrated flow (subject to user Dispatch Confirmation at phase boundaries). |

There is no CLI flag on `claude_turn.sh` / `codex_turn.sh` for this; the **parent agent** reads `ROUNDTABLE_STOP_AFTER_PLAN_PHASE` and gates Phase B.

**User checkpoint (recommended after Phase A):** Present `artifacts/options.md`, confirm which option(s) to carry forward, then run Phase B with a tight `--task` for the aggregator.

---

## Phase A — Research / options (read-only bias)

**Goal:** N parallel planners or discussant-framed turns from **different actor families** produce partial option artifacts; one synthesis turn merges them into **`artifacts/options.md`** — a cross-vendor option matrix with explicit trade-offs. Phase A is **not** required to pick a single winner; the user may still choose after reading the matrix.

1. **Create thread**: `new_thread.sh <slug> "<goal>"` (optional `QUESTION.md` for purely exploratory questions).
2. **Confirm dispatch**: Show the root [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation). `Multi?` should list N parallel planners from **different actor families** (e.g. codex + claude + cursor-subagent) per Hard Rule #4. Pick actors manually from `backend.sh show`; there is no automated `--diversity` flag.
3. **Fan-out**: Dispatch N `planner` (or `discussant`) turns in parallel with tasks that require option matrices / plans written under `artifacts/` **without** mandating a final unified `PLAN.md` yet. All three planner backends are now write-protected and the per-vendor plan body is captured into `artifacts/plan-<actor>-<ts>.md` by the dispatcher, so a single glob `artifacts/plan-*-<ts>.md` collects every fan-out for the synthesis step:
   - **Claude**: `claude_turn.sh` uses `--permission-mode plan`; capture writes `artifacts/plan-claude-<ts>.md`.
   - **Codex**: `codex_turn.sh` uses `--sandbox read-only` for planner role (P1.1); capture writes `artifacts/plan-codex-<ts>.md`.
   - **Cursor subagent**: the chat parent (NOT a shell script) is responsible for the capture. After `Task(subagent_type=…, model=…)` returns, write the subagent's final 5-part body to `artifacts/plan-cursor-<ts>.md` *before* calling `append_turn.sh`. Use the same `<ts>` you pass to `--ts` for `append_turn.sh` so the artifact name lines up with the thread turn entry.
4. **Synthesis (single actor)**: One high-capability turn merges `artifacts/options-*.md` / planner stubs into **`artifacts/options.md`**. Keep merge clerical: deduplicate, preserve dissent, attribute sources; **do not** smuggle a final “winner” if the user has not asked for Phase B yet.

**Phase A alone** matches the old “discuss” intent: options and trade-offs, user decides.

---

## Phase B — Aggregate master plan

**Goal:** One aggregator reads `artifacts/options.md`, `GOAL.md`, and the codebase, then writes **`artifacts/PLAN.md`** — a single executable plan with steps, risks, and verification hooks.

1. **Confirm dispatch** for the aggregation turn (single planner or `reviewer-aggregator`-style task with planner prompts).
2. **Fan-in**: Run one turn whose explicit deliverable is `artifacts/PLAN.md`.
3. **Hand-off**: Present `PLAN.md` and ask whether to proceed to `roundtable-execute` or `roundtable-goal`.

---

## Parallel planners (full two-phase recap)

### Fan-out (Phase A and/or per-planner drafts for B)

- **Diversity is required** across vendors for independent perspectives.
- Each agent reads the codebase and goal; writes into `history/` and/or `artifacts/` per task.

### Aggregation (Phase B)

- **Role**: `planner` with an aggregate `--task`, or a dedicated synthesis role.
- **Actor**: High reasoning + long context (e.g. `claude-opus`, `cursor-claude-4.7-opus`).
- **Output**: Final **`artifacts/PLAN.md`**.

## Step-by-step (typical)

1. **Create thread**: `new_thread.sh <slug> "<goal>"`
2. **Confirm dispatch**: N parallel planners — include Model Awareness specs.
3. **Execute fan-out**: Run turn scripts (parallel tool calls per substrate docs).
4. **Wait** until all complete.
5. **Phase A synthesis** → `artifacts/options.md` (if not already produced per planner).
6. **Checkpoint**: If `ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a`, stop here and wait for the user.
7. **Confirm aggregation**: Dispatch Confirmation for the single aggregator turn.
8. **Phase B** → `artifacts/PLAN.md`
9. **Hand-off**: Offer `roundtable-execute` or `roundtable-goal`.

## Related

- Deprecated alias: old `roundtable-discuss` → **this skill** with Phase A only (`ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a`).
- Execution: `skills/roundtable-execute/SKILL.md`. Convergence loop: `skills/roundtable-goal/SKILL.md`.
