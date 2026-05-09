---
name: roundtable-execute
description: Use when N parallel cross-vendor executors should each implement the SAME task on isolated branches, then a blind aggregator picks the single best candidate.
---

# Roundtable Execute

Race N executors from different actor families against the same `GOAL.md` on isolated worktrees, then run `roundtable-review`'s aggregator over the resulting candidate branches and select the single best implementation. The output is N committed branches plus an aggregator verdict justifying the winner against acceptance criteria.

## Use when

- Multiple high-quality candidate implementations are genuinely valuable: risky changes (auth, schema, perf-critical loops, novel API design) where seeing different shapes informs the merge decision.
- Speed-via-racing: the user accepts paying N× tokens to compress wallclock and dodge a bad single bet.
- The executor pool can plausibly disagree — well-defined task, but multiple defensible designs.
- Prior single-executor attempts produced a working-but-ugly answer and the user wants alternative shapes to compare.

## Don't use when

- Trivial work — one-line fixes, mechanical renames, formatting. The dispatch + aggregator overhead dominates.
- You want **iteration to a single answer**, not selection among candidates — that is `roundtable-goal` (single executor, planner → review loop).
- The right approach is unsettled and you don't yet know what task to assign — use `roundtable-discuss` first to lock the option, then come back here or pipeline into `roundtable-goal`.
- You only want a verdict, no code changes — use `roundtable-review`.
- `models.json` only has one actor family configured; cross-vendor independence requires ≥2 families. Bounce to `roundtable-setup`.

## Why N parallel cross-vendor executors

Cross-family independence is the lever. Empirically, executors trained by different vendors disagree ~99% of the time on open-ended generation, vs ~48% for "think critically" prompts within a family (arXiv 2604.07650) — N executors from N families produce more diverse solutions than N executors from the same family, period.

The DEBATE / multi-agent-debate literature also says it explicitly: independent generation **before** any cross-talk is the only reliable way to get genuinely different proposals; once agents see each other's drafts, sycophancy collapses the candidate set (arXiv 2509.23055). That is why this sub-skill issues all N executor turns from worktrees that cannot see each other — no shared `THREAD.md` reads, no cross-agent prompts. The aggregator is the **first** moment any candidate is exposed to the others, and it judges, it does not synthesize.

## The process

### Phase 0: confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) block from the root SKILL.md once. The `Multi?` line should read explicitly e.g. `N parallel executors: codex + claude` (or `+ cursor-subagent`). Wait for user approval (or an explicit "go").

For N parallel executors, the estimator must be invoked once per actor and the per-actor bands summed in the confirmation block (e.g. `Est. : $0.05 + $1.20 + $0.30 = $1.55–$5.40/round`); a single per-turn band understates the cost by N× and was the original 20x miss this script exists to fix.

### Phase 1: isolate worktrees, dispatch N executors concurrently

Each executor gets its own branch via `git worktree`. They share the same `--task` and the same `GOAL.md`, but never see each other's commits or threads.

```
slug=<thread-slug>
git -C $ROUNDTABLE_PROJECT_ROOT worktree add ../$slug-codex   -b $slug/codex
git -C $ROUNDTABLE_PROJECT_ROOT worktree add ../$slug-claude  -b $slug/claude

ROUNDTABLE_PROJECT_ROOT=../$slug-codex   $SKILL/scripts/codex_turn.sh  $slug --role executor --task "<the same task one-liner>"
ROUNDTABLE_PROJECT_ROOT=../$slug-claude  $SKILL/scripts/claude_turn.sh $slug --role executor --task "<the same task one-liner>"
```

Run them concurrently (background or parallel `Task` dispatch). `--blind` is **not** used here — these are executors, not reviewers; they don't share context anyway because the worktrees isolate them. All N turns must finish before Phase 2.

### Phase 2: aggregator picks the single best candidate

Run the cross-vendor blind aggregator (per `roundtable-review`'s contract) over the N candidate branches. Tell it explicitly to **select**, not synthesize.

```
$SKILL/scripts/claude_turn.sh $slug --role reviewer-aggregator \
  --task "Compare candidate branches: $slug/codex, $slug/claude (and any others). Select the SINGLE best candidate. Justify by evidence_delta against GOAL.md acceptance criteria. Do NOT propose a Frankenstein merge; pick one branch as-is."
```

The aggregator's `verdict.json` records the chosen branch, the per-candidate scoring, and any `dissenting_concerns`.

### Phase 3: hand the winner to the user

Surface the chosen branch, the aggregator verdict path, and the losing branches' SHAs. Do not delete the losing branches — they are forensic record (for skill-of-failure review or for the user to cherry-pick a specific idea later).

## Red flags / Stop when

- All executors come from the same actor family — abort and re-dispatch with cross-vendor pairs. Same-family parallel runs fail the independence premise.
- Any executor returns `Hand-off: escalate-to-user` — surface immediately, do not silently drop that candidate from selection. The user decides whether to proceed without it or revise the task.
- Aggregator returned a synthesized "merge of A and B" instead of selecting one branch — re-dispatch the aggregator with stricter "select, do not merge" framing.
- Executors stomped on each other (e.g. forgot to use worktrees and committed to the same branch) — abort, redo Phase 1.
- Aggregator verdict has no `evidence_delta` per candidate — verdict is unjustified; re-dispatch.

## Hand off

- **User merges the winning branch.** For merge mechanics see `superpowers:finishing-a-development-branch`.
- **Winner needs polishing** (BLOCKER count low but acceptance has PARTIAL items) — pipeline into `roundtable-goal` on the winning branch to converge.
- **All candidates failed acceptance** — the task spec is wrong or the goal is unachievable at current model capability; escalate to user before burning more rounds.
