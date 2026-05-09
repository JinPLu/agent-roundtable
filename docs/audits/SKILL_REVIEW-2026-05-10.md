# agent-roundtable — skill review (vs. create-skill principles)

> Reviewer: cursor-claude-4.7-opus  (Opus 4.7 thinking-high)
> Date: 2026-05-10
> Scope: full skill — `SKILL.md`, `docs/`, `roles/`, `scripts/`, `models.example.json`, `README.md`
> Standard: `/root/.cursor/skills-cursor/create-skill/SKILL.md`

## TL;DR

- **Biggest issue — incoherence between SKILL.md and `docs/`.** Three of the four `docs/` files contain stale claims that contradict the current code: a "known bugs" list flagging fixed bugs (`resolve_model`, `append_turn.sh` devils-advocate gap, devils-advocate `pass` field), a *wrong* five-part body template in `MODEL-CAPABILITY-GUIDE.md` (`Summary/Read/Plan/Verification/Next` instead of `Read/Did/Verification/Open questions/Hand-off`), and model-registry rows pointing at private aliases (`codex-gpt-5`, `claude-opus → DeepSeek-V4-Pro`) that don't exist in the shipped `models.example.json`. An agent that follows these docs will produce malformed turns or call non-existent aliases.
- **Biggest strength — `SKILL.md` itself is clean (176 lines), well-scoped, and obeys the create-skill principles.** Description is third-person with strong trigger terms; dispatch confirmation block, five-part body, and hard rules are concrete; progressive disclosure to `docs/{advanced,SCRIPTS-ANALYSIS,MODEL-CAPABILITY-GUIDE}.md` is one level deep; `disable-model-invocation: true` is set; `_as_of` pricing handled with a contract instead of hard-coded dates.
- **Recommended next step — fix `docs/` rather than touching `SKILL.md`.** The recent rewrite (commit `aa1053f`) made `SKILL.md` good. The patch debt has migrated into `docs/` (stale bug claims) and `route.py` (private aliases hardcoded into `FALLBACKS`). One concentrated `docs/` cleanup pass would resolve ≥4 of the top-5 findings without changing protocol.

---

## Per-principle scores

| #  | Principle                                         | Score | Note |
|----|---------------------------------------------------|-------|------|
| 1  | Description quality                               | PASS  | Third-person, WHAT+WHEN, strong trigger terms ("dispatching tasks to two or more LLM actors", "cross-actor audit trail", "convergence loop"). |
| 2  | Concise                                           | PASS  | `SKILL.md` is dense, table-heavy, no obvious filler. Setup section is minimal (≈25 lines). |
| 3  | `SKILL.md` ≤ 500 lines                            | PASS  | 176 lines including frontmatter. |
| 4  | Progressive disclosure / one level deep           | WARN  | All linked docs are one level deep. But `docs/FILE-INVENTORY.md` is **not linked** from `SKILL.md` (orphan); `roles/reviewer.schema.json` is referenced from `SKILL.md` only by name (not as a link). |
| 5  | Appropriate degrees of freedom                    | PASS  | Hard rules low-freedom; routing high-freedom ("treat as starting points, not decisions"); deterministic prompt assembly scripted. Calibration is good. |
| 6  | Consistent terminology                            | WARN  | "actor" / "agent" mixed; "chat parent" / "orchestrator" mixed; "five-part body" / "five-part turn body" / "five-part block" / "five-part output" all appear. None are confusing in isolation but they pile up. |
| 7  | No time-sensitive info                            | WARN  | `SKILL.md` itself handles this well (delegates pricing to `_as_of`). But `docs/MODEL-CAPABILITY-GUIDE.md` lines 154-162 hard-code GPT-5.5/DeepSeek prices, and `docs/FILE-INVENTORY.md` line 4 has `Generated: 2026-05-10` (will rot once a file changes). |
| 8  | Anti-patterns                                     | WARN  | No Windows paths, no too-many-options, names are concrete. **But:** stale bug-warnings in `docs/` are the equivalent of time-sensitive copy that has rotted, and `route.py` hard-codes private aliases (`claude-opus`, `gpt-5.5`) into a `FALLBACKS` dict — a vague-name / private-state leak. |
| 9  | Examples concrete & complete                      | PASS  | Dispatch confirmation block, five-part body template, JSON verdict schema, setup JSON skeleton are all complete and copy-pasteable. |
| 10 | Coherence (SKILL.md ↔ docs/ ↔ roles/ ↔ scripts/)  | FAIL  | Multiple contradictions; this is the dominant problem. Detailed below. |

---

## Per-principle findings (expanded)

### 4. Progressive disclosure — WARN

- `SKILL.md:176` links to `docs/SCRIPTS-ANALYSIS.md`, `docs/MODEL-CAPABILITY-GUIDE.md`, `docs/advanced.md`. ✅ one level deep.
- `docs/FILE-INVENTORY.md` is **not** linked from `SKILL.md`. It exists primarily to support audit-by-AI workflows; if that's the intent, document it; otherwise consider removing or linking it.
- `models.example.json` is linked from `SKILL.md:50`. ✅
- `roles/reviewer.schema.json` is mentioned in `SKILL.md:124` (Hard rules) by name only — not via link. The role prompts (`reviewer.system.md`, `devils-advocate.system.md`) point at it via `<SKILL_DIR>/roles/reviewer.schema.json`. Consider a literal link from `SKILL.md`.

### 6. Consistent terminology — WARN

| Concept | Variants observed | Recommendation |
|---|---|---|
| The non-human side of a turn | "actor" (table headers), "agent" (Hard rule #1, README), "agent CLI" (README) | Pick one for prose ("actor" matches the JSON field); reserve "agent" for the roundtable narrative ("agent-roundtable", "agents disagree"). |
| The orchestrator | "chat parent" (`SKILL.md` × 4), "orchestrator" (role prompts × 5, `advanced.md` × 1) | Pick "chat parent" (it's already in the skill name's mental model) or document them as synonyms once. |
| The mandatory output unit | "five-part turn body", "five-part block", "five-part body", "five-part output", "five-part Read/Did/Verification/Open-questions/Hand-off entry" | Pick "five-part turn body" everywhere. |
| Cursor subagents | "Cursor subagent" (SKILL.md), "Cursor Task subagent" (advanced.md, README), "cursor-subagent" (actor JSON value) | Three forms is fine if each has a role (prose / dispatch / actor key) — document the convention once. |

### 7. No time-sensitive info — WARN

- `docs/MODEL-CAPABILITY-GUIDE.md:154-162` ("Cost reference") hard-codes specific provider prices ("GPT-5.5 (cialloapi) | ~$0.069 | ~$0.069 | ~70x cheaper than official OpenAI", "DeepSeek-V4-Pro | ~$0.14 | ~$0.87"). The same file at line 162 says "Pricing changes frequently. Always check `models.json`" — so the table contradicts its own caveat. **Either delete the table or move it under a `<details>` block tagged with an `_as_of` date.**
- `docs/FILE-INVENTORY.md:4` `Generated: 2026-05-10` — fine as long as the file is regenerated; otherwise drop the date.

### 8. Anti-patterns — WARN

- `scripts/lib/route.py:16-20` hard-codes `FALLBACKS` with private workspace-specific aliases (`gpt-5.5`, `claude-opus`). A user who installs the skill cleanly and runs `route.sh --role reviewer` may hit a fallback path that names aliases not present in their `models.example.json`. This is a private-state leak from the maintainer's `models.json` into shipped logic. Mirrors the `MODEL-CAPABILITY-GUIDE.md` issue below.
- `models.example.json:44-53` `_template` placeholder uses `REPLACE_WITH:codex_or_claude` etc. — good pattern. `_status` strings are long (60-100 words) and mix imperative voice with prose; trim where possible to keep the JSON readable in editors.

### 10. Coherence — FAIL (dominant issue)

#### 10a. Stale "Known bugs" lists

`_common.sh:351-373` already implements the corrected `resolve_model` (iterates over alias arrays, matches `actor`). `append_turn.sh:87` already includes `devils-advocate` in the verdict-extraction branch. `roles/devils-advocate.system.md:54` already explicitly says "Do not add a `pass` field — the schema does not define one." Yet:

- `docs/FILE-INVENTORY.md:88-93` "Known bugs" lists all three issues as open ("`resolve_model` schema mismatch", "`append_turn.sh` devils-advocate gap", "`devils-advocate.system.md` schema prose bug").
- `docs/SCRIPTS-ANALYSIS.md:42-46` "Known bug" subsection: same `resolve_model` claim with workaround "always pass `-m MODEL`".
- `docs/SCRIPTS-ANALYSIS.md:192-196` "Fix needed: Add `devils-advocate` to the role check in step 4" — already done.
- `docs/MODEL-CAPABILITY-GUIDE.md:66-73` step 4 ("Always pass `-m MODEL` explicitly") — workaround for a fixed bug.

This is dangerous: an agent reading `docs/` will be told the skill is broken when it isn't, and may avoid the auto-resolve path that now works correctly.

#### 10b. `docs/MODEL-CAPABILITY-GUIDE.md:39-58` shows the WRONG five-part body

Lines 39-58 show:

```
**Summary**
**Read**
**Plan**
**Verification**
**Next**
```

The actual contract everywhere else (`SKILL.md:144-152`, all five `roles/*.system.md`) is:

```
**Read** → **Did** → **Verification** → **Open questions** → **Hand-off**
```

This is a critical contradiction: an agent following `MODEL-CAPABILITY-GUIDE.md` will emit a five-part body that fails `append_turn.sh`'s parser. Section §2 ("The five-part block must be the entire final message") is also titled inconsistently with the rest of the skill.

#### 10c. `docs/MODEL-CAPABILITY-GUIDE.md:18-27` model registry uses private aliases

The shipped `models.example.json` exposes aliases: `gpt-5.5`, `gpt-5.3-codex`, `claude-4.7-opus`, `claude-4.6-sonnet`, `cursor-composer-2`, `cursor-claude-4.7-opus`, `cursor-claude-4.6-sonnet`, `cursor-gemini-3.1-pro`.

`MODEL-CAPABILITY-GUIDE.md:22-27` lists `codex-gpt-5`, `claude-opus`, `cursor-composer-2`, `cursor-claude-4.7-opus`, `cursor-claude-4.6-sonnet`, `cursor-gemini-3.1-pro`. Two of those (`codex-gpt-5`, `claude-opus`) only exist in the maintainer's gitignored `models.json`. `claude-opus` is described as backed by `DeepSeek-V4-Pro`, which is a workspace-specific shim choice.

This is the same private-state leak as `route.py`'s `FALLBACKS`. A clean install of the skill cannot honour these references.

#### 10d. `README.md:34` example dispatches `--model opus`

```
$SKILL/scripts/claude_turn.sh my-review --role reviewer --model opus --bare
```

No alias `opus` exists in `models.example.json` (`claude-4.7-opus` does). `SKILL.md:19` uses `-m gpt-5.5` (which does exist). README and SKILL examples should align on shipped aliases.

#### 10e. `docs/advanced.md:100-104` orphan numbering

"Known sharp edges (additional)" begins at item **3.** with no items 1 or 2. Suggests a copy-paste from a longer list. Fix numbering or remove the heading.

#### 10f. Three role prompts duplicate the same anti-trust paragraph

`planner.system.md:18`, `executor.system.md:18`, `discussant.system.md:18` each have a near-identical "Trust nothing from prior turns" rule with slightly different wording. Same intent in `reviewer.system.md:14-19` and `devils-advocate.system.md:24-29` (longer). Either factor a `roles/_shared_rules.md` snippet (low-freedom skills are allowed shared partials) or accept duplication and standardise wording — but pick one.

---

## Top 5 improvements (ranked by leverage)

### 1. Fix the wrong five-part template in `docs/MODEL-CAPABILITY-GUIDE.md`

- **What**: Replace `MODEL-CAPABILITY-GUIDE.md:39-58` (`**Summary** / **Read** / **Plan** / **Verification** / **Next**`) with the canonical `**Read** / **Did** / **Verification** / **Open questions** / **Hand-off**`. Cross-check the rest of the file for similar drift.
- **Why**: Coherence-FAIL. Following this section produces output that `append_turn.sh` rejects. Highest-blast-radius bug because it silently breaks turns.
- **Effort**: 1-line / small refactor (≤10 minutes).

### 2. Delete the stale "Known bugs" sections from `docs/`

- **What**: Remove the `Known bugs` block at `FILE-INVENTORY.md:88-93`; remove the `Known bug` subsection at `SCRIPTS-ANALYSIS.md:42-46` and the `Fix needed` line at `SCRIPTS-ANALYSIS.md:196`; remove `MODEL-CAPABILITY-GUIDE.md:66-73` (step 4 "Always pass `-m MODEL` explicitly"); update inventory rows that still say "Fix" to "Keep".
- **Why**: Coherence-FAIL. The documented bugs are fixed in code (`_common.sh:351-373`, `append_turn.sh:87`, `devils-advocate.system.md:54`). Leaving stale claims in tells agents to apply workarounds for non-existent bugs and may discourage use of the now-working auto-resolve path.
- **Effort**: small refactor — touches three files but is mechanical.

### 3. Make `docs/MODEL-CAPABILITY-GUIDE.md` and `route.py` honour `models.example.json`

- **What**:
  - Replace the model-registry table at `MODEL-CAPABILITY-GUIDE.md:18-27` with rows that match aliases shipped in `models.example.json` (or describe alias *categories* rather than concrete names, e.g. "your Codex executor alias").
  - Drop or `<details>`-wrap the `Cost reference` table at `MODEL-CAPABILITY-GUIDE.md:154-162` (or move it to `models.example.json` `pricing` blocks where it already exists).
  - Soften `route.py`'s `FALLBACKS` (lines 16-20): when the registry has no entries for a role, log a warning ("no aliases registered for role X; pass `-m` explicitly") instead of falling back to private aliases.
- **Why**: Anti-pattern (private-state leak) + time-sensitive info. A cleanly-installed skill should not reference the maintainer's gitignored `models.json` aliases.
- **Effort**: small refactor.

### 4. Standardise terminology and align `SKILL.md` ↔ `README.md` examples

- **What**:
  - Sweep "five-part body / block / turn / output" → **five-part turn body** (single canonical phrase). Same for "chat parent" vs "orchestrator" — pick "chat parent".
  - Update `README.md:34` example from `--model opus` to a real alias (`claude-4.7-opus` if intended for the example registry).
  - Document the actor-naming convention in one sentence ("actor JSON value: `cursor-subagent`; prose: Cursor Task subagent; informal: Cursor subagent").
- **Why**: create-skill anti-pattern #4 (inconsistent terminology) + concrete example completeness. Small but cumulative friction.
- **Effort**: small refactor — single-pass find-and-replace plus one example fix.

### 5. Consolidate role-prompt boilerplate

- **What**: The "Trust nothing from prior turns" rule is duplicated in `planner.system.md`, `executor.system.md`, `discussant.system.md`, and (in expanded form) `reviewer.system.md`, `devils-advocate.system.md`. Either:
  - Promote the canonical wording from `executor.system.md:18` and replace all variants verbatim, OR
  - Extract a `roles/_independence_rule.md` partial that each role file `<!-- includes -->` (and SKILL.md's prompt assembly inlines once) — this also lets `_common.sh:`build_prompt`'s "stable prefix" stop carrying the same advice (`_common.sh:226-228`).
- **Why**: DRY across role prompts; reduces drift risk; same advice currently appears in three places (`SKILL.md` Hard rule #1, `_common.sh` stable prefix, each role file). Token cost is non-trivial because role prompts ship into every Claude turn via `--append-system-prompt`.
- **Effort**: small refactor to medium (depends on whether you wire a partial-include or just standardise wording).

---

## Strengths to preserve

- **`SKILL.md` is the right size and shape.** 176 lines, table-heavy, every section earns its keep. Don't expand it.
- **Description is exemplary.** Third-person, both WHAT and WHEN, strong trigger terms. Use it as a model for other skills in the repo.
- **`disable-model-invocation: true`** correctly set — this skill should only load when explicitly named.
- **Dispatch confirmation block** (`SKILL.md:54-77`) is concrete, copy-pasteable, and the most important UX guarantee in the skill. Keep its prominence.
- **Hard rules** (`SKILL.md:114-126`) are short, numbered, and enforceable — ideal create-skill style.
- **Pricing freshness contract** (`models.example.json:_readme` + `_as_of` per `pricing` block) is a clean way to handle inherently rotting data without dating the skill itself. Best-in-class pattern.
- **Five-part turn body example** lives where it should (in `SKILL.md` Reference). Don't move it to a doc file.
- **`build_prompt` ordering** (`_common.sh:178-205`) is well-documented for cache stability; the comments are an authoring win for future maintainers.
- **`emit_done` two-layer signal** (stdout marker + sentinel file) is a thoughtful contract that simplifies parallel-dispatch coordination — keep it.
- **Schema-strict reviewer JSON** (`reviewer.schema.json`, `additionalProperties: false`) plus the convergence-loop optional-fields whitelist in `reviewer.system.md:70-93` is exactly the right calibration of low-freedom + extension hatch.

---

## Open questions for the user

1. **Keep `docs/FILE-INVENTORY.md`?** It's not linked from `SKILL.md`. If it's a one-shot audit artifact, move it to a `meta/` or `audits/` folder (or delete after fixes). If it's the maintainer's living index, link it from `SKILL.md` and keep it dated.
2. **Was `docs/MODEL-CAPABILITY-GUIDE.md` written against the maintainer's private `models.json` or against `models.example.json`?** The model-registry table and cost reference suggest the former. Decide which the *shipped* doc should describe (recommendation: `models.example.json` aliases or no concrete aliases at all).
3. **Should `route.py`'s `FALLBACKS` ship with example aliases at all?** Cleaner alternative: refuse to fall back, emit "no aliases registered for role; pass `-m` explicitly". Up to you whether that breaks expected `route.sh` smoke-test behaviour.
4. **Should `SKILL.md` link to `roles/reviewer.schema.json` directly** (rather than mention by name)? Minor, but improves the one-level-deep contract.
5. **Has the `claude-opus` / `claude-sonnet` aliases-route-to-DeepSeek note** (`advanced.md:102`) outlived its usefulness now that the example registry uses `claude-4.7-opus` / `claude-4.6-sonnet` directly? If yes, drop the note; otherwise clarify which file the note refers to.
