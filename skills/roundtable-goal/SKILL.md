---
name: roundtable-goal
description: Use when pursuing a feature or refactor to convergence — pure orchestration over roundtable-plan → roundtable-execute → roundtable-review with budget, stall, and scope handling.
disable-model-invocation: true
---

# Roundtable Goal

**Pure orchestrator.** This skill does not redefine planning, execution, or review — it **sequences** the other sub-skills and scripts:

| Phase | Delegated sub-skill | Primary scripts / outputs |
|-------|---------------------|---------------------------|
| Plan | `skills/roundtable-plan/SKILL.md` | `codex_turn.sh` / `claude_turn.sh` → `artifacts/PLAN.md`, optionally Phase A `artifacts/options.md` |
| Execute | `skills/roundtable-execute/SKILL.md` | `codex_turn.sh` / `claude_turn.sh` as `executor` → working tree + optional `artifacts/EXEC_REPORT.md`; parent runs **scope check** from that skill |
| Review | `skills/roundtable-review/SKILL.md` | parallel `reviewer` + `devils-advocate` (`--blind`), then `reviewer-aggregator` → `verdict.json` |

Every turn is still appended to `THREAD.md` with a full audit trail. The **loop control** below is unique to Goal.

## Use when

- Multi-file feature work or refactor where you want a paper trail and cross-vendor verification.
- High-risk changes where one-shot execution is too risky.
- The user asks for "the quality loop" / "convergence loop" / "full roundtable".
- Prior single-actor execution stalled or produced inconsistent results.

## Do not use when

- A one-line fix — the loop overhead dominates; edit or one executor turn.
- The user wants to ship fast and accepts quality risk — say so explicitly.
- **Multiple candidate implementations** — use the opt-in race pattern in [`docs/advanced.md`](../../docs/advanced.md#n-parallel-executors-race--opt-in), not this loop’s default path.
- Open strategy — use **`roundtable-plan`** first (Phase A `options.md`, then Phase B `PLAN.md`).
- `models.json` is unconfigured — `roundtable-setup`.

## Why the loop

Three disciplines single-shot execution skips: (1) **plan before code** (`roundtable-plan`); (2) **cross-vendor blind verification** (`roundtable-review`); (3) **convergence-by-evidence** — the aggregator emits `convergence_status`, `next_action_hint`, `evidence_delta_vs_prior_round`.

---

## Loop control responsibilities (only Goal owns these)

The following are **orchestrator duties** — not delegated to plan/execute/review skills as standalone guarantees:

- **Budget** — `max-rounds`, `max-turns`, `max-wallclock` from Dispatch Confirmation; enforce before starting another round.
- **Stall detection** — unchanged verdict / no evidence delta across rounds (tie-break per Phase 5).
- **Scope revert instruction** — when `scope_violation.detected` is true in the verdict, direct the **next execute** to revert listed paths before new work (same as today’s schema contract).
- **Convergence policy** — when to stop, loop to execute only, loop to plan, or escalate.

---

## The process

### Phase 0: confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) once at the start. Set **Budget** if desired (default: 3 rounds, no clock cap). Subsequent phases inside one accepted run do not need re-confirmation unless scope changes catastrophically.

### Phase 1: plan (`roundtable-plan`)

Follow **`skills/roundtable-plan/SKILL.md`**:

- Fan-out N parallel **planner** turns (cross-vendor), then Phase B aggregation to **`artifacts/PLAN.md`**.
- For short exploratory loops you may set `ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a` and pause at **`artifacts/options.md`** before continuing to Phase B — document that in the thread when used.

Example entrypoints (pick actors per `route.sh`):

```bash
$SKILL/scripts/codex_turn.sh  <slug> --role planner --task "<goal one-liner>"
$SKILL/scripts/claude_turn.sh <slug> --role planner --task "…"
```

Wait until `PLAN.md` (and `GOAL.md` acceptance criteria) align with user intent. If `GOAL.md` is still the template, sharpen inputs and re-invoke plan.

### Phase 2: execute (`roundtable-execute`)

Follow **`skills/roundtable-execute/SKILL.md`** — **single executor** in the main worktree:

```bash
$SKILL/scripts/codex_turn.sh  <slug> --role executor --task "<derived from aggregator or PLAN.md>"
# or claude_turn.sh
```

After the turn completes, run the **scope check** prescribed there (`git diff --name-only` vs `GOAL.md` **In-scope paths**). Surface violations before treating the round as successful.

### Phase 3: parallel blind review (`roundtable-review`)

Follow **`skills/roundtable-review/SKILL.md`** — cross-vendor, **`--blind`**:

```bash
$SKILL/scripts/codex_turn.sh  <slug> --role reviewer        --blind
$SKILL/scripts/claude_turn.sh <slug> --role devils-advocate --blind
```

Both must finish before Phase 4.

### Phase 4: aggregate

```bash
$SKILL/scripts/claude_turn.sh <slug> --role reviewer-aggregator \
  --task "Round N convergence verdict; emit convergence_status."
```

### Phase 5: evaluate stop condition

Before starting a new round, run `python3 scripts/lib/check_budget.py <thread_dir>` to verify the budget cap has not been reached *(Hard Rule #8)*.

Read **`verdict.json`**:

- **Stop and report success** if `blocking_issues` has 0 BLOCKERs **and** acceptance shows ≤1 PARTIAL/MISSING/VERIFICATION-NOT-EVIDENCED **and** `convergence_status` is `converged` or `progressing → accept-and-stop`.
- **Fast-fail (anti-stall)** if `evidence_delta_vs_prior_round == "none"` AND blocking issues are unchanged from the previous round — do **not** dispatch another executor; surface stall.
- **Scope-violation revise** if `scope_violation.detected == true` — loop to Phase 2 with `--task` to revert paths in `scope_violation.paths` before further feature work.
- **Loop to Phase 2** otherwise — pass `next_action_hint` into the executor `--task`.
- **Budget hit** — escalate with latest verdict; do not start another round.
- **Escalate** if `convergence_status` is `stalled` two rounds running, or `regressed`.

## Red flags / stop when

- Three rounds without converged or accept-and-stop — escalate.
- Executor `Hand-off: escalate-to-user` — surface immediately.
- Reviewer without `--blind` — verdict contaminated; re-run that reviewer.
- Scope check after execute shows out-of-scope files — treat as violation surface before accepting progress.

## Hand off

On convergence, report final `verdict.json`, commit summary (`git log <thread-start-sha>..HEAD`), and point to `superpowers:finishing-a-development-branch`.

Related: **`roundtable-plan`** (options + plan), **`roundtable-execute`** (single implementation + scope surface), **`roundtable-review`** (verdict-only), **`docs/advanced.md`** (parallel executor race).
