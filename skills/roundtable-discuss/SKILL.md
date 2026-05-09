---
name: roundtable-discuss
description: Use when an open-ended design question needs cross-vendor research that surfaces options and trade-offs without converging on a recommendation.
---

# Roundtable Discuss

Run N discussants from different actor families against the same open question, in parallel, with no instruction to converge. Each produces an option matrix; a single synthesis turn merges them into `artifacts/options.md` — a cross-vendor option matrix the **user** reads and decides on. The output of this sub-skill is the matrix, not a winner.

## Use when

- Open-ended design questions: "Redis or Postgres for X?", "best library for Y?", "JWT vs session cookies?", "monorepo or polyrepo?".
- Pre-implementation research where you want trade-offs surfaced before committing to a plan.
- Architectural splits where reasonable practitioners would disagree and you want the disagreement visible.
- The user says "I don't know what the right shape of this feature is yet" or "give me options."

## Don't use when

- You already have a chosen approach and want to implement it — go to `roundtable-goal` (single executor convergence) or `roundtable-execute` (N parallel candidate implementations).
- You just need a yes/no critique of an existing artifact — that is `roundtable-review`.
- You want a single-agent Socratic Q&A with the user to clarify requirements — use `superpowers:brainstorming` instead. Brainstorming is single-agent dialogue with the user; discuss is multi-vendor parallel research the user reads. They are complementary: brainstorm to crystallise the question, then discuss to map the option space.
- The question is small and one model is plainly enough. Run a single `discussant` turn and stop.
- `models.json` only has one actor family configured. Bounce to `roundtable-setup`.

## Why parallel cross-vendor without converging

Cross-family independence (arXiv 2604.07650): different vendors disagree ~99% vs ~48% within-family on open-ended generation, so N discussants from N families surface a wider option set than N discussants from the same family.

The **never-converge** part matters too. Multi-agent debate fails when sycophancy collapses agents onto a single early proposal — the failure-mode survey explicitly recommends keeping debate participants from instructing each other toward consensus on open questions (arXiv 2509.23055). Discuss therefore takes the principle seriously: the synthesis turn merges and de-duplicates options but is **prompted not to pick a winner**. The user picks.

## The process

### Phase 0: confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) block from the root SKILL.md once. The `Multi?` line should read e.g. `N parallel discussants: codex + claude`. Wait for user approval (or explicit "go").

### Phase 1: pose the question

Write `$ROUNDTABLE_PROJECT_ROOT/.roundtable/threads/<slug>/QUESTION.md` containing the open question, any context (links, prior decisions, constraints), and the explicit instruction "list options with explicit pro / con / risk / when-to-pick. Do NOT recommend." `GOAL.md` is not required for discussion threads.

> TODO (not in this task's scope): the existing `roles/discussant.system.md` already says "Present options with explicit trade-offs rather than a single recommendation," but it does not yet hard-wire a `QUESTION.md` lookup the way executor roles hard-wire `GOAL.md`. Until that is added, pass the question via `--task` *and* commit `QUESTION.md` so future discussants can read it from disk.

### Phase 2: dispatch N discussants concurrently from different vendors

```
$SKILL/scripts/codex_turn.sh  <slug> --role discussant --task "Read QUESTION.md. Produce artifacts/options-codex.md with options + pro/con/risk/when-to-pick. Do NOT recommend."
$SKILL/scripts/claude_turn.sh <slug> --role discussant --task "Read QUESTION.md. Produce artifacts/options-claude.md with options + pro/con/risk/when-to-pick. Do NOT recommend."
```

Run concurrently. They do not see each other (independent turns, no `--blind` flag needed because no prior verdict block exists for discussants). All N must finish before Phase 3.

### Phase 3: synthesis turn (single high-capability actor, NOT multi-vendor)

```
$SKILL/scripts/claude_turn.sh <slug> --role discussant \
  --task "Merge artifacts/options-*.md into artifacts/options.md as one option matrix. Deduplicate, preserve dissent, attribute each option to its source actor(s). Do NOT pick a winner — the user picks."
```

Synthesis is intentionally single-agent: this is a clerical merge, not another opinion. Multi-vendor synthesis would re-introduce sycophancy at the merge step.

## Red flags / Stop when

- Synthesis output ends with a recommendation or a "best option" verdict — re-dispatch synthesis with stricter framing. Discuss never recommends.
- All discussants converge on the same option with the same reasoning — likely shared training-data correlation; re-dispatch with a more diverse vendor set or accept the convergence and move on.
- Any discussant tried to write code or modify the working tree — that's an executor leaking through; abort that turn, the role was misconfigured.
- A discussant returned `Hand-off: escalate-to-user` (the question is outside thread scope) — surface immediately.

## Hand off

Present `artifacts/options.md` to the user verbatim. Then ask which option they want to pursue, and route accordingly:

- "I'll commit to option X" → `roundtable-goal` (single converging implementation of the chosen option).
- "I want to see X and Y both implemented and compare" → `roundtable-execute` (N parallel candidates of the chosen options).
- "I want X reviewed before deciding" → `roundtable-review` against any existing artifact for X.
- "I need to think more / refine the question" → `superpowers:brainstorming` (single-agent Socratic refinement) and re-run discuss after.
