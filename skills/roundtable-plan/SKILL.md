---
name: roundtable-plan
description: Use when the user wants to create a robust implementation plan, architecture design, or step-by-step strategy. Dispatches N parallel planners across different vendors, then synthesizes a master plan.
---

# Roundtable Plan

Use when the user wants to create a robust implementation plan, architecture design, or step-by-step strategy for a complex task, and wants to leverage cross-vendor perspectives before committing to code.

## The Flow

### 1. Parallel Planners (Fan-out)
Dispatch N (usually 2 or 3) parallel agents using the `planner` role.
- **Diversity is required**: Use different actor families (e.g., one Codex, one Claude, one Cursor subagent). Run `route.sh --role planner --diversity` to find candidates.
- Each agent reads the codebase and the user's goal, then writes its proposed plan to the thread's `history/` directory.

### 2. Aggregation (Fan-in)
Once the parallel planners complete, dispatch a single aggregator to synthesize them.
- **Role**: `planner` (with a custom `--task` instructing it to aggregate) or `reviewer-aggregator`.
- **Actor**: Use a high-reasoning, long-context model (e.g., `claude-opus` or `cursor-claude-4.7-opus`).
- **Task**: Read the N proposed plans from the history, resolve conflicts, pick the best approaches from each, and write a final, unified `PLAN.md` to the thread's `artifacts/` directory.

## Step-by-Step

1. **Create Thread**: `new_thread.sh <slug> "<goal>"`
2. **Confirm Dispatch**: Show the standard Dispatch Confirmation block for the N parallel planners. *Ensure you include the Model Awareness specs (benchmarks, price, notes).*
3. **Execute Fan-out**: Run the turn scripts in the background (`&`).
4. **Wait**: Monitor the thread until all planners finish.
5. **Confirm Aggregation**: Show a Dispatch Confirmation for the aggregator turn.
6. **Execute Fan-in**: Run the aggregator turn.
7. **Hand-off**: Present the final `PLAN.md` to the user and ask if they want to proceed to `roundtable-execute` or `roundtable-goal`.
