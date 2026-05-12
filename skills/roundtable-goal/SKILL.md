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

## Autonomy contract (read this first)

`/roundtable-goal` is **self-driving**. The single user touchpoint is the **Phase 0 Dispatch Confirmation** — it binds budget + actors + target. After GO, the loop **MUST NOT** ping the user via `AskQuestion` until one of the three hard stops fires (budget hit / executor `escalate-to-user` / converged success). Every other recovery — stall, scope violation, regression, single reviewer failure, route 5xx — is handled by **dispatching another agent**, not by interrupting the user.

The cross-vendor substrate exists exactly for this: when output is wrong, **the next turn (different actor + blind) is the corrective signal**, not the human.

| Failure mode | Auto-recovery (no user ping) |
|---|---|
| Verdict `scope_violation.detected` | Auto-dispatch executor with `--task "revert <paths> then re-implement per PLAN.md"` |
| Stall (`evidence_delta_vs_prior_round == "none"` + same blockers) | Auto-dispatch a **diagnostic planner** turn (different actor than last executor): `--task "Diagnose why round N didn't progress. Output a revised next_action_hint."` Then continue with that hint. |
| Regression (`convergence_status == "regressed"`) | Same as stall: diagnostic planner round. |
| Single CLI reviewer fails (5xx / timeout) | Auto-fallback to the corresponding `cursor-*` route for **that one reviewer**, log the swap in `THREAD.md`. The other (cross-vendor) reviewer stays put — diversity is preserved. **No `AskQuestion`** for review-time route swaps (the per-turn `Failover requires re-confirm` rule in root SKILL.md applies to standalone turns, not to in-loop substitutions). |
| `next_action_hint` empty or vacuous | Re-dispatch the aggregator first (might have dropped signal). If still empty, treat as stall. |

The **3 hard stops** that DO touch the user (and the only AskQuestion shapes inside the loop):

1. **Budget cap hit** — `check_budget.py` returns non-zero. Surface latest verdict + commit summary. AskQuestion: `extend-1-round / accept-current / abort`.
2. **Executor body has `Hand-off: escalate-to-user`** — the model itself is asking. Surface verbatim. No options imposed; the executor's question is the question.
3. **Converged success** — report final verdict + diff; not a question, just a summary.

Everything else: the loop self-corrects via cross-vendor turns and writes evidence to `THREAD.md` / `verdict.json` for post-hoc inspection.

---

## Loop control responsibilities (only Goal owns these)

- **Budget enforcement** — `check_budget.py` before each new round.
- **Stall / scope / regression recovery** — auto-dispatch the appropriate corrective turn per the table above.
- **Cross-vendor invariant** — when a reviewer fallback happens, the *pair* must still be cross-vendor; never let both reviewers collapse to the same family.
- **Convergence detection** — read `convergence_status` + `blocking_issues` + acceptance map.

---

## The process

### Phase 0: confirm dispatch (the only mandatory user touchpoint)

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) **once**. Set **Budget** explicitly (default: 3 rounds, no clock cap) — this is the **autonomy envelope**; the loop will not ping again until budget is exhausted. Subsequent in-loop turns do **not** re-confirm, even when the loop substitutes a fallback route or auto-dispatches a corrective turn.

### Phase 1: plan

Delegate to **`skills/roundtable-plan/SKILL.md`** (cross-vendor fan-out → `artifacts/PLAN.md`). Goal-loop constraint: if `GOAL.md` acceptance criteria are still at template defaults, sharpen them and re-invoke plan before proceeding to Phase 2.

### Phase 2: execute

Delegate to **`skills/roundtable-execute/SKILL.md`** (single executor, main worktree). Before Phase 1, if the user edited a Cursor plan outside the thread, auto-run **`import_plan.sh <plan-path> --slug <slug>`** so `artifacts/PLAN.md` matches the reviewed file.

Goal-loop overrides standalone-execute behaviour:

- After the executor turn, run `python3 $SKILL/scripts/lib/scope_check.py --thread <slug>`.
- On `VIOLATION` → **do NOT call AskQuestion**. Auto-dispatch the next executor turn with `--task "Revert these out-of-scope paths: <paths>. Then re-implement the same step per artifacts/PLAN.md within In-scope paths only."` Then re-run scope_check on the new diff. Two consecutive VIOLATIONs on the same round = treat as stall (Phase 5 diagnostic planner).
- On `NO_GOAL` → auto-dispatch a planner turn with `--task "GOAL.md In-scope paths is empty; populate it from PLAN.md before the next executor round."` Then retry Phase 2.
- After `scope_check == PASS`, run the oracle gate. If any `must_pass` oracle fails, do **not** proceed to review; auto-dispatch executor with `--task "Fix oracle <name>: <stdout_tail>"`, then re-run execute + scope + oracle.

### Phase 3: parallel blind review

Delegate to **`skills/roundtable-review/SKILL.md`** (cross-vendor, `--blind`). Both reviewers must finish before Phase 4.

### Phase 4: aggregate

Delegate to the `reviewer-aggregator` role per **`skills/roundtable-review/SKILL.md`**. Aggregator output lands in `verdict.json`; proceed to Phase 5.

### Phase 5: evaluate stop condition (mostly silent)

Before starting a new round, run `python3 scripts/lib/check_budget.py <thread_dir>` *(Hard Rule #5)*.

Read **`verdict.json`** + the executor body from `THREAD.md` and dispatch the next action **without asking the user**:

| Condition | Action |
|---|---|
| `convergence_status == "converged"` AND `blocking_issues` has 0 BLOCKERs AND ≤1 PARTIAL/MISSING/VERIFICATION-NOT-EVIDENCED | **Stop, report success** to user (final summary, not a question). |
| `scope_violation.detected == true` | Auto-loop to Phase 2 with `--task "revert <scope_violation.paths> then re-implement in-scope"`. No AskQuestion. |
| Stall (`evidence_delta_vs_prior_round == "none"` AND same blockers as last round) | Auto-dispatch a **diagnostic planner** (cross-vendor vs the last executor): `--task "Round N stalled. Diagnose root cause of unchanged blockers <list>. Output revised next_action_hint."` Use its hint for the next Phase 2. |
| `convergence_status == "regressed"` | Same as stall. Diagnostic planner first. |
| 2 stalls in a row (diagnosis didn't help) | Auto-loop to Phase 1 (re-plan) with `--task "Two consecutive rounds stalled; re-evaluate PLAN.md against current code state."` |
| `next_action_hint` empty | Auto re-dispatch aggregator. If still empty: treat as stall. |
| Otherwise (progressing) | Auto-loop to Phase 2 with `next_action_hint` as `--task`. |

### Phase 6: extract lessons (only after convergence)

When the loop reaches converged success, call `scripts/lib/lessons_extract.py` for the current thread so project memory records the final blockers / drift / scope lessons. This is a post-convergence maintenance step, not part of the normal recovery loop.

### The only AskQuestion the loop is allowed to emit

Fired **only** when `check_budget.py` returns non-zero (budget envelope from Phase 0 is exhausted):

```
AskQuestion(
  prompt="预算 <N> 轮已用完。<latest verdict summary>. 下一步？",
  options=[
    {id: "extend",       label: "再加 1 轮 (重新计预算)"},
    {id: "accept",       label: "接受当前状态，commit summary"},
    {id: "abort",        label: "回退所有未 commit 改动"},
  ],
)
```

The other allowed user touchpoint is **executor self-escalation**: when the executor body contains `Hand-off: escalate-to-user: <question>`, surface that question verbatim — do **not** wrap it in a multi-option AskQuestion; the model is asking a specific thing.

## Red flags / stop when

- Reviewer without `--blind` — verdict contaminated; auto-re-run that reviewer (do NOT surface).
- Cross-vendor invariant broken (both reviewers from same family after a fallback) — auto-re-dispatch the second reviewer on a different family before the aggregator.
- Executor `Hand-off: escalate-to-user` — surface immediately (the only mid-loop user touchpoint besides budget cap).
- Budget cap hit — `check_budget.py` non-zero — surface as above.

## Hand off

On convergence, report final `verdict.json`, commit summary (`git log <thread-start-sha>..HEAD`), and point to `superpowers:finishing-a-development-branch`.

Related: **`roundtable-plan`** (options + plan), **`roundtable-execute`** (single implementation + scope surface), **`roundtable-review`** (verdict-only), **`docs/advanced.md`** (parallel executor race).
