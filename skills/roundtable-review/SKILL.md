---
name: roundtable-review
description: Use when reviewing code, auditing security, checking a PR, or finding bugs and the user wants cross-vendor blind reviewers and an aggregated verdict — not a single-model review.
disable-model-invocation: true
---

# Roundtable Review

> The chat parent orchestrates; this sub-skill never auto-dispatches (see root [SKILL.md](../../SKILL.md)).

Run two or more reviewers from different actor families against the same target, in parallel, blind to each other's verdicts, then dispatch an aggregator that produces one defensible merged judgement. The output is a structured JSON verdict (per `roles/reviewer.schema.json`) that downstream tooling can parse.

## Use when

- The user explicitly asks for a cross-vendor or "second opinion" review.
- A high-stakes change is about to land (security, auth, payments, migrations).
- A single-model review came back "looks good" and you suspect modal sycophancy.
- The user wants an audit trail (every reviewer's prompt, output, verdict.json on disk).

## Don't use when

- A small change where one reviewer is sufficient — overkill, wastes tokens. Run a single `claude_turn.sh ... --role reviewer` instead.
- **You also want to make code changes.** Reviewers are read-only. To act on findings use `roundtable-execute` (N parallel candidate fixes) or `roundtable-goal` (plan → execute → review convergence loop). This sub-skill stops at the verdict by design.
- **You want a full plan→execute→review loop, not a one-shot verdict.** That is `roundtable-goal`'s contract — it owns iteration; this sub-skill does not.
- You haven't run `roundtable-setup` and `models.json` is missing. Bounce to that sub-skill first.
- The change is exploratory / unfinished. Reviewers need stable artifacts to evaluate; review when the executor's turn is complete, not mid-stream.

## Why blind, why cross-vendor

Empirical result (arXiv 2605.00914): when reviewer agents see a prior reviewer's verdict, they adopt it ~85% of the time regardless of whether it's correct — modal adoption sycophancy. Two same-vendor reviewers correlate even without seeing each other (shared training data). The substrate counters both:

- **Cross-vendor** (e.g. one Codex, one Claude) breaks shared-training correlation. Independent assignment yields ~99% disagreement vs ~48% for "think critically" instructions (arXiv 2405.09935).
- **`--blind`** suppresses the prior-verdict block in the prompt assembly, killing modal adoption.

Skipping either one defeats the design.

## The process

### 1. Confirm dispatch

Show the [Dispatch Confirmation](../../SKILL.md#dispatch-confirmation) block from the root SKILL.md. Wait for user approval (or an explicit "go").

### 2. Pick the target

Identify the file(s), commit range, or PR the user wants reviewed. Update `GOAL.md` in the thread with the acceptance criteria — reviewers grade against `GOAL.md`, not against your chat-parent intuition.

### 3. Dispatch parallel reviewers (different actor families, both `--blind`) *(Hard Rule #5)*

```
$SKILL/scripts/codex_turn.sh  <slug> --role reviewer        --blind --task "Review <target>"
$SKILL/scripts/claude_turn.sh <slug> --role devils-advocate --blind --task "Review <target>"
```

Run them concurrently (background or parallel `Task` dispatch). Both reviewers must finish before the aggregator runs.

### 4. Dispatch the aggregator

```
$SKILL/scripts/claude_turn.sh <slug> --role reviewer-aggregator \
  --task "Select the most defensible verdict; preserve dissent."
```

The aggregator is **not** a tiebreaker — it deduplicates findings, takes worst-case acceptance per criterion, promotes the highest-severity issue per merged finding, and records minority dissent in `dissenting_concerns`.

### 5. Report

Read the aggregator's `verdict.json` from its `history/<actor>/<ts>/verdict.json`. Surface:

- The top blocking issues (BLOCKER + MAJOR), with file:line evidence.
- Acceptance breakdown (COVERED / PARTIAL / MISSING / VERIFICATION-NOT-EVIDENCED).
- Any scope violation.
- Any dissenting concern the aggregator did not promote.

## Red flags / Stop when

- Both reviewers are from the same actor family — abort, re-dispatch with a cross-vendor pair.
- Either reviewer ran without `--blind` — its verdict is contaminated; re-run.
- The aggregator returned `accept` while a parallel reviewer returned `revise` and you cannot find the dissent in `dissenting_concerns` — the aggregator dropped a signal; re-dispatch the aggregator.
- Reviewer turns ran with write permissions — a non-reviewer role was used. Re-dispatch.

## Hand off

Present the merged verdict to the user with a one-line recommendation: `accept` / `revise` / `escalate-to-user`. Do **not** auto-fix BLOCKERs — that is `roundtable-execute` (N candidate fixes) or `roundtable-goal` (single converging fix) territory. If the user wants to act on findings, hand off to one of those so the loop can continue with the same audit trail.
