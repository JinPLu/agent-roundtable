---
name: roundtable-develop
description: Use when implementing a feature, refactoring, or running the full quality loop (plan → execute → parallel blind review → aggregate → loop) on a non-trivial change with cross-vendor verification.
---

# Roundtable Develop

The full quality loop. A `planner` writes `artifacts/plan.md`, an `executor` implements it, two cross-vendor reviewers (`reviewer` + `devils-advocate`, both `--blind`) verify, a `reviewer-aggregator` produces the merged verdict, and the loop iterates until the stop condition is met. Every turn is appended to `THREAD.md` with full audit trail.

## Use when

- Multi-file feature work or refactor where you want a paper trail.
- High-risk changes (security, schema migrations, build-system overhauls) where one-shot execution is too risky.
- The user explicitly asks for "the quality loop" / "convergence loop" / "full roundtable".
- Prior single-actor execution stalled or produced inconsistent results.

## Don't use when

- A one-line fix or a trivial rename — the loop overhead dominates the work. Use a single `executor` turn or just edit directly.
- The user wants to ship fast and accepts the quality risk — surface that trade-off and let them choose. Consider `superpowers:subagent-driven-development` instead, which has lower review overhead.
- `models.json` is unconfigured — bounce to `roundtable-init`.

## Why the loop

Three disciplines single-shot execution skips: (1) **plan before code** so reviewers grade against `GOAL.md` not vibes; (2) **cross-vendor blind verification** to catch modal blind spots — see `roundtable-review` for the empirical basis; (3) **convergence-by-evidence** — the aggregator emits `convergence_status` / `next_action_hint` / `evidence_delta_vs_prior_round` so the loop exits on evidence, not on "looks good".

## The process

### Phase 0: confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) block from the root SKILL.md once at the start. Subsequent phases inside one accepted run do not need re-confirmation unless a phase fails catastrophically or the user changes scope.

The user may set a **Budget** line in the confirmation block (`max-rounds=N | max-turns=M | max-wallclock=Xm`). If unset, default is 3 rounds with no clock cap. The parent agent enforces the budget: exceeding any of the three bounds escalates immediately (skip Phase 2 re-dispatch, surface the latest aggregator verdict and the budget hit). Budget enforcement is a documented protocol, not a script — count rounds / turns / wallclock as you orchestrate.

### Phase 1: plan

```
$SKILL/scripts/codex_turn.sh <slug> --role planner --task "<goal one-liner>"
```

Wait for completion. The planner produces `artifacts/plan.md` and updates `GOAL.md` with acceptance criteria. Read `GOAL.md` after the turn — if it's still the template, re-dispatch with sharper input.

### Phase 2: execute

```
$SKILL/scripts/codex_turn.sh <slug> --role executor
# or claude_turn.sh, depending on the model the user picked for executor
```

Wait for completion. Inspect `git diff --stat` in the project root. The executor's five-part body is in `THREAD.md`; the actual code change is in the working tree.

### Phase 3: parallel blind review (cross-vendor)

```
$SKILL/scripts/codex_turn.sh  <slug> --role reviewer        --blind
$SKILL/scripts/claude_turn.sh <slug> --role devils-advocate --blind
```

Both must come from different actor families. Both must use `--blind`. Both must finish before Phase 4. (Run concurrently.)

### Phase 4: aggregate

```
$SKILL/scripts/claude_turn.sh <slug> --role reviewer-aggregator \
  --task "Round N convergence verdict; emit convergence_status."
```

The aggregator's `verdict.json` carries the loop-control signal.

### Phase 5: evaluate stop condition

Read the aggregator's `verdict.json`:

- **Stop and report success** if `blocking_issues` has 0 BLOCKERs **and** `acceptance` shows ≤1 PARTIAL/MISSING/VERIFICATION-NOT-EVIDENCED **and** `convergence_status` is `converged` or `progressing → accept-and-stop`.
- **Fast-fail to user (anti-stall)** if `evidence_delta_vs_prior_round == "none"` AND the set of `blocking_issues[].id` (or `blocking_issues[].issue` text when `id` is absent) is unchanged from the previous round. Do NOT dispatch another executor turn — this is a stalled goal, not an effort problem; surface the aggregator's last `next_action_hint` and the unchanged BLOCKERs.
- **Scope-violation revise** if `scope_violation.detected == true`. Loop back to Phase 2 with `--task` instructing the executor to revert the listed out-of-scope changes (paths from `scope_violation.paths`) before any further work. This branch overrides convergence signals — out-of-scope writes are never accepted.
- **Loop back to Phase 2** otherwise. Pass the aggregator's `next_action_hint` into the executor's `--task` so it knows what to fix.
- **Budget hit** — if any of `max-rounds`, `max-turns`, or `max-wallclock` from Phase 0 is exceeded after evaluating this round, escalate immediately with the latest verdict; do not start another round.
- **Escalate to user** if `convergence_status` is `stalled` for two consecutive rounds, or `regressed`. Loops that don't converge are a planner / model-capability problem, not an executor effort problem; surface this rather than burning more rounds.

## Red flags / Stop when

- Three rounds without a `converged` or `accept-and-stop` signal — escalate. Either the plan is wrong or the model is under-powered.
- Executor reports `Hand-off: escalate-to-user` — do not skip; surface immediately.
- `git diff --stat` shows changes outside `In-scope paths` from `GOAL.md` — scope violation; revert or re-scope before continuing.
- Reviewer dispatched without `--blind` — verdict is contaminated; re-run that reviewer only.

## Hand off

On convergence, report the final aggregator `verdict.json` path, the commit summary (`git log <thread-start-sha>..HEAD`), and point the user at `superpowers:finishing-a-development-branch` for merge / PR mechanics.

Related: `roundtable-review` (verdict-only, no plan/execute), `superpowers:subagent-driven-development` (fresh-subagent loop, no on-disk audit trail).
