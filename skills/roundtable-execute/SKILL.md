---
name: roundtable-execute
description: Use when a single executor should implement artifacts/PLAN.md (from import_plan.sh, Cursor, or roundtable-plan) plus GOAL.md, with mandatory post-run scope check.
disable-model-invocation: true
---

# Roundtable Execute

> The chat parent orchestrates; this sub-skill never auto-dispatches (see root [SKILL.md](../../SKILL.md)).

**Single-executor** implementation. One `executor` turn (or a short sequence of executor turns) carries out `GOAL.md` and/or `artifacts/PLAN.md` in the project working tree. When the work is done, the **orchestrating parent** (not the model) runs a **scope check** and surfaces any out-of-scope paths before you merge or hand off to review.

> **Advanced:** N parallel executors on isolated worktrees with an aggregator pick-winner is an **opt-in pattern** — see [../../docs/advanced.md#n-parallel-executors-race--opt-in](../../docs/advanced.md#n-parallel-executors-race--opt-in).

## Use when

- You have a settled plan **`artifacts/PLAN.md`** (from `import_plan.sh`, Cursor, or `roundtable-plan` Phase B) and a filled-in **`GOAL.md`** (**In-scope paths**, **Definition of done**) and need one implementation pass.
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

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) from the root `SKILL.md` *(Hard Rule #2 — generate via `print_dispatch_block.py`)*. `Multi?` is **single executor** unless you explicitly opt into the advanced race pattern.

### Phase 1: implement

1. **Plan snapshot (required when the canonical plan lives outside the thread)**  
   If the user’s plan is a Cursor file (`~/.cursor/plans/*.plan.md` or similar) or any path outside `<thread>/artifacts/`, run **`import_plan.sh`** *before* dispatch so **`artifacts/PLAN.md`** is a byte-accurate copy and `GOAL.md` **Plan source** lists the **Original source path** and **Last imported at**:

   ```bash
   # Single arg — slug auto-derived (filename + YYYYMMDD), thread auto-created
   bash $SKILL/scripts/import_plan.sh /absolute/path/to/plan.md [--reviewed yes|no|N/A]

   # Override slug when re-importing into an existing thread
   bash $SKILL/scripts/import_plan.sh /absolute/path/to/plan.md --slug <slug> --reviewed yes
   ```

   If you already edited `artifacts/PLAN.md` in-repo and that is the only source of truth, ensure **Original source path** in `GOAL.md` says `in-thread only` and **Last imported at** is accurate or `N/A`.

2. Ensure `GOAL.md` lists **In-scope paths** and **Out-of-scope** (see `templates/GOAL.md.tmpl`). The plan body must align with those paths.

3. Dispatch one executor turn. The `--task` MUST explicitly require reading the plan before edits, e.g.:

   ```bash
   $SKILL/scripts/codex_turn.sh  <slug> --role executor \
     --task "Read <thread_dir>/artifacts/PLAN.md in full (and GOAL.md). Then implement step-by-step in plan order; cite plan section titles in Did:."
   ```

   (Adjust wording if `artifacts/PLAN.md` is genuinely absent — executor falls back to `GOAL.md` + task only.)

4. Wait for completion. Inspect the five-part body in `THREAD.md` and the actual diff in the repo.

5. **Optional:** ask the executor to add `artifacts/EXEC_REPORT.md` (what changed, how to verify, follow-ups) — not required by the scripts but useful for hand-off.

### Phase 2: scope check (orchestrator / parent — required)

After the executor turn finishes, run:

```bash
python3 $SKILL/scripts/lib/scope_check.py --thread <slug>
```

Pass `--base <sha>` if you want to diff from a specific commit other than the auto-detected merge-base. The script reads `GOAL.md`'s **In-scope paths** and **Out-of-scope** sections and compares them against `git diff --name-only`.

- Exit 0 (`PASS`) → state that the scope check passed and proceed.
- Exit 1 (`VIOLATION`) → do **not** silently accept the work. Call:

  ```
  AskQuestion(
    prompt="Scope 违规，怎么办？",
    options=[
      {id: "revert",              label: "Revert out-of-scope 文件，re-run executor"},
      {id: "accept-update-goal",  label: "接受变更，更新 GOAL.md In-scope 范围"},
      {id: "re-plan",             label: "回到 roundtable-plan 重新规划"},
    ],
  )
  ```

- Exit 2 (`NO_GOAL`) → GOAL.md is missing or its In-scope section is empty; fill it before re-running.

This check is **not** an automatic git revert — the parent/user decides the action via the AskQuestion above.

## Red flags / stop when

- `Hand-off: escalate-to-user` in the executor body — stop and surface.
- Scope check finds out-of-scope files — do not treat the run as “done” until addressed.
- No `In-scope paths` in `GOAL.md` — fill them before execution or accept that scope checks are manual-only.

## Hand off

- **Converge further** — `roundtable-goal` if you want planner/review loops.
- **Review only** — `roundtable-review` on the resulting diff.
- **Merge** — `superpowers:finishing-a-development-branch` when acceptance criteria pass.
