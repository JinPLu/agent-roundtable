---
name: roundtable-execute
description: Use when a single executor should implement artifacts/PLAN.md (or GOAL.md) in the main worktree, with a mandatory post-run scope check surfaced to the user.
disable-model-invocation: true
---

# Roundtable Execute

**Single-executor** implementation. One `executor` turn (or a short sequence of executor turns) carries out `GOAL.md` and/or `artifacts/PLAN.md` in the project working tree. When the work is done, the **orchestrating parent** (not the model) runs a **scope check** and surfaces any out-of-scope paths before you merge or hand off to review.

> **Advanced:** N parallel executors on isolated worktrees with an aggregator pick-winner is an **opt-in pattern** — see [../../docs/advanced.md#n-parallel-executors-race--opt-in](../../docs/advanced.md#n-parallel-executors-race--opt-in).

## Use when

- You have a settled plan (`artifacts/PLAN.md` from `roundtable-plan`, or a filled-in `GOAL.md`) and need one implementation pass.
- You want execution with an audit trail in `THREAD.md` and a clear **post-exec scope surface** (see below).
- The user is not asking for multiple competing candidate implementations (that race pattern is `docs/advanced.md`).

## Do not use when

- Trivial one-line fixes where the roundtable dispatch overhead is unnecessary — edit directly or a single ad-hoc turn.
- You need **iteration to convergence** with blind review — use `roundtable-goal` (or execute once then hand to goal).
- You only want a verdict on existing code — `roundtable-review`.
- The approach is still undecided — run `roundtable-plan` (Phase A and/or B) first.
- `models.json` is unconfigured — `roundtable-setup`.

## The process

### Phase 0: confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) from the root `SKILL.md`. `Multi?` is **single executor** unless you explicitly opt into the advanced race pattern.

### Phase 1: implement

1. Ensure `GOAL.md` exists in the thread and lists **In-scope paths** and **Out-of-scope** (see `templates/GOAL.md.tmpl`). Plans from `roundtable-plan` should align with these paths.
2. Dispatch one executor turn, e.g.:

```bash
$SKILL/scripts/codex_turn.sh  <slug> --role executor --task "<concrete task from PLAN.md / GOAL.md>"
# or
$SKILL/scripts/claude_turn.sh <slug> --role executor --task "…"
```

3. Wait for completion. Inspect the five-part body in `THREAD.md` and the actual diff in the repo.

4. **Optional:** ask the executor to add `artifacts/EXEC_REPORT.md` (what changed, how to verify, follow-ups) — not required by the scripts but useful for hand-off.

### Phase 2: scope check (orchestrator / parent — required)

The executor turn itself does not prove scope compliance. After the turn finishes, the **parent agent** must:

1. Fix a **comparison base** — e.g. the commit at thread start, or the SHA recorded when the plan was accepted (`<plan-base-sha>`). Document which base you use in the thread or `OPEN_QUESTIONS.md` if ambiguous.
2. List touched paths:

   `git -C <ROUNDTABLE_REPO_ROOT> diff --name-only <plan-base-sha>..HEAD`

3. Parse **In-scope paths** from `GOAL.md` (prefixes or glob patterns as written there). Any changed path that does **not** fall under an in-scope rule is a **scope violation candidate** (also cross-check **Out-of-scope**).

4. **Surface** the result to the user explicitly:
   - If all paths are in scope → state that the scope check passed.
   - If any path is out of scope → list those paths, link to `GOAL.md` sections, and **do not** silently accept the work; follow `roundtable-goal` / user direction to revert or re-scope.

This check is the **single-execute** equivalent of the scope signal used inside the goal loop; it is **not** an automatic git revert (the parent/user decides).

## Red flags / stop when

- `Hand-off: escalate-to-user` in the executor body — stop and surface.
- Scope check finds out-of-scope files — do not treat the run as “done” until addressed.
- No `In-scope paths` in `GOAL.md` — fill them before execution or accept that scope checks are manual-only.

## Hand off

- **Converge further** — `roundtable-goal` if you want planner/review loops.
- **Review only** — `roundtable-review` on the resulting diff.
- **Merge** — `superpowers:finishing-a-development-branch` when acceptance criteria pass.
