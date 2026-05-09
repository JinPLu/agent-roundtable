---
name: roundtable-develop
description: Implement complex features or refactors using the full quality loop (Plan -> Execute -> Parallel Review -> Aggregate). Use when the user asks to develop a feature, refactor code, or implement a complex task using agent-roundtable.
---

# Roundtable Develop

This skill encapsulates the "Full Quality Loop" mode of `agent-roundtable`.

## Workflow

When the user asks to implement a feature:

1. **Phase 1: Plan**
   - Dispatch a `planner` agent to break down the task and create a plan in `artifacts/plan.md`.
   - Wait for completion.
2. **Phase 2: Execute**
   - Dispatch an `executor` agent to implement the plan.
   - Wait for completion.
3. **Phase 3: Parallel Review**
   - Dispatch at least TWO parallel reviewers (e.g., `reviewer` and `devils-advocate`) from different vendors with the `--blind` flag.
   - Wait for both to complete.
4. **Phase 4: Aggregate**
   - Dispatch a `reviewer-aggregator` to evaluate the reviews.
5. **Evaluate Stop Condition**:
   - If the aggregator reports `BLOCKER`s or >1 objections, loop back to Phase 2 (Execute) to fix the issues.
   - If 0 BLOCKERs and ≤1 objection, the loop is complete. Report success to the user.

## Rules
- Always use the mandatory dispatch confirmation block before starting the loop.
- You do not need to ask for confirmation between phases of the loop unless a phase fails catastrophically.
- Ensure `ROUNDTABLE_PROJECT_ROOT` is set correctly.