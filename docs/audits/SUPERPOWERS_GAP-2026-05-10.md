# agent-roundtable — Superpowers-pattern gap audit

> Date: 2026-05-10
> Reference: `/root/.cursor/plugins/cache/cursor-public/superpowers/.../skills/`
> Authoring guide: `/root/.cursor/skills-cursor/create-skill/SKILL.md`
> Goal: identify how the current suite drifts from the superpowers pattern and
> propose a clean refactor that preserves all real capability.

## 1. Pattern observations (what superpowers does well)

1. **Flat sub-skill folders, verb-phrase or activity-named.** `dispatching-parallel-agents/`, `executing-plans/`, `subagent-driven-development/`, `verification-before-completion/`. No `skills/` nested inside skills.
2. **Terse third-person `description` in YAML frontmatter** that names *when* (e.g. "Use when facing 2+ independent tasks…"). It's a trigger, not a summary.
3. **Each sub-skill is self-sufficient prose protocol.** It explains the *why* (Overview / Core principle), *when* (Use when / Don't use when), the *how* (numbered process, often with a `dot` graph), and *handoff* (Integration with other skills).
4. **Red Flags / Stop conditions / "When NOT to Use" sections** are first-class. They frame the skill as a discipline, not a recipe.
5. **Cross-references by skill name, not file path.** `superpowers:requesting-code-review`, not `../requesting-code-review/SKILL.md`.
6. **Almost no shell scripts** — the skill *is* the protocol. (Agent-roundtable is an exception: scripts are the actual machinery and must stay.)
7. **The router (`using-superpowers/SKILL.md`) is short, principle-driven**: a `dot` graph of "should I invoke a skill?", a Red Flags table, no execution detail.
8. **Diagrams are sparing** (one or two per skill, in `dot`), and used for branching decisions.

## 2. Gap analysis (per file)

### `SKILL.md` (root, 54 lines) — partial pass
- ✅ Already dispatches to sub-skills (progressive disclosure works).
- ✅ `disable-model-invocation: true` set.
- ⚠ `description` is two sentences and reads more like a summary than a trigger. Superpowers descriptions are one terse "Use when …" clause.
- ⚠ "Roles and Scripts" block at the end mixes router with reference material — superpowers routers don't ship reference. Move role/script details to the sub-skills that actually use them.
- ⚠ Core Principles list is good but item 1 (Mandatory Confirmation) and the dispatch block belong together as a single named section so sub-skills can cite "see Dispatch Confirmation in root SKILL.md".

### `README.md` (98 lines) — too marketing-y, emoji-heavy
- ⚠ Heavy emoji header (🤝 ✨ 🚀 💡 🎭 📁 📄 🛡️ 📝 🔓 🔒 🧹) — superpowers READMEs would not do this.
- ⚠ Dual feature lists: "核心特性" + "协作模式" + "6 种预设角色" table all duplicate content that lives more authoritatively in `SKILL.md` and `roles/*.system.md`.
- ⚠ The roles table here is the *only* user-facing summary of all six roles, but it duplicates info in `roles/`. Pick one home (here is fine — it's user docs).
- ✅ Bilingual contract honoured (Chinese for human readers).
- ✅ Quick Start is concrete (clone path + initialize prompt + apply).

### `skills/roundtable-init/SKILL.md` (32 lines) — too thin
- ⚠ Just a 3-step procedural checklist. No "Use when / Don't use when", no red flags, no handoff section. A user reading this in isolation can run the steps but doesn't learn the *discipline*.
- ⚠ Hard-codes `~/.cursor/skills/agent-roundtable/scripts/backend.sh` — should use `$SKILL_DIR` or describe the script by name like the root does.
- ⚠ Doesn't mention `ROUNDTABLE_PROJECT_ROOT` semantics (the user's project root vs the skill's own dir) — that's a foot-gun the script warns about.

### `skills/roundtable-review/SKILL.md` (34 lines) — too thin, partial coverage
- ⚠ Same shape as init: bare workflow, no discipline framing.
- ⚠ Mentions `--blind` and "different vendors" but does not explain *why* (the 85.5% modal-adoption sycophancy result the codebase cites elsewhere). The "why" lives only in `_common.sh` comments.
- ⚠ "Always use the mandatory dispatch confirmation block before running the scripts, unless the user explicitly said 'go' or 'dispatch now'." — the second clause silently relaxes the root SKILL.md's hard rule. Either tighten the root rule to allow this exception or remove the relaxation here.
- ⚠ No "Don't use when" — e.g. when one model is genuinely sufficient, blind cross-vendor is overkill.

### `skills/roundtable-develop/SKILL.md` (31 lines) — too thin
- ⚠ 4-phase recipe with no failure modes, no "what if executor reports BLOCKED?", no convergence-loop background. The convergence-loop optional fields are documented in `roles/reviewer.system.md` but a develop-mode reader has no pointer.
- ⚠ Stop condition ("0 BLOCKERs and ≤1 objection") is a magic number with no rationale; needs either a one-line "why" or a link to the design doc.
- ⚠ Doesn't reference `superpowers:subagent-driven-development` even though they solve overlapping problems differently.

### `roles/*.system.md` — fine, leave as-is
- These are agent-facing system prompts, not skills. The `_independence_rule.md` factoring is good. No changes needed except the audit confirms they belong here.

### `scripts/*.sh` — fine, do not touch (per user constraint)
- The capability surface (`--blind`, `ROUNDTABLE_PROJECT_ROOT` resolution, blind-mode addendum suppression, role-system-prompt injection, `extract_json_verdict`) is all real and must stay reachable from the new structure.

### `docs/`
- `advanced.md` and `MODEL-CAPABILITY-GUIDE.md` are appropriate one-level-deep references; keep.
- `audits/SKILL_REVIEW-2026-05-10.md` and `audits/FULL_POWER_AUDIT-2026-05-10.md` are prior audits — keep as historical record.
- `audits/FILE-INVENTORY-2026-05-10.md` is an orphan (not linked) — leave for audit-AI use.

## 3. Refactor proposal

### Rename / restructure
- **Keep current sub-skill names** (`roundtable-init`, `roundtable-review`, `roundtable-develop`). They're already consistent and the prefix `roundtable-` keeps them grouped if they ever flatten into a sibling skill registry. Verb-phrasing (`-reviewing`, `-developing`) would not improve clarity here.
- **Keep the nested `skills/` folder** — Cursor's plugin scan picks up the inner SKILL.md files (the user already has them registered as separate skills in `<available_skills>`). Flattening would break installed-skill enumeration.

### Root `SKILL.md` (target: 50–70 lines)
- Tighten `description` to one "Use when …" trigger clause.
- Promote the dispatch confirmation block to a named section ("## Dispatch Confirmation") so sub-skills can cite it.
- Keep the five core principles; rename to "Hard rules (apply to every sub-skill)".
- Drop the trailing "Roles and Scripts" reference block — move role/script names into the relevant sub-skill.
- Keep the "Read sub-skill X for intent Y" router table.

### Sub-skills (target: 50–80 lines each)
Each adopts the superpowers shape:
1. Tight one-line `description` with "Use when …".
2. **Use when / Don't use when** section.
3. **Why** (one paragraph stating the discipline being enforced — for review, the cross-vendor anti-sycophancy result; for develop, the convergence-loop rationale; for init, the full-blood-agent context-injection point).
4. **The Process** (numbered, with concrete script invocations using `$SKILL/scripts/...`, env hints).
5. **Red flags / Stop when** section.
6. **Handoff** (what to report back to the user / which sub-skill is next).

### `README.md` (target: ~80 lines, Chinese)
- Drop emoji density to 0–2 (one for the title is fine; not on every section header).
- Remove "核心特性" bullet list (duplicates SKILL.md hard rules).
- Keep the 6-role table (it's the only user-facing roles summary).
- Compact "协作模式" into a single paragraph; the four modes are already explained in `docs/advanced.md`.
- Keep file-structure section but simplify.

### Files to delete / merge
- **None.** Every file pulls weight. Even `models.example.json` is the contract surface for the routing logic.

## 4. Risks & capability preservation

The following capabilities must NOT regress; each is preserved by the refactor:

| Capability | Currently lives in | Preserved by |
|------------|--------------------|--------------|
| Cross-vendor blind review (`--blind`) | `roundtable-review/SKILL.md` + `_common.sh` | Stays in `roundtable-review` with strengthened "why" framing |
| Context hygiene (update AGENTS.md / .planning/) | root `SKILL.md` + every role prompt | Stays in root hard rules + role prompts (unchanged) |
| Dispatch confirmation block | root `SKILL.md` | Promoted to named section in root |
| Minimal tool disablement (only destructive git blocked) | root `SKILL.md` + `claude_turn.sh` | Stays in root hard rules |
| `ROUNDTABLE_PROJECT_ROOT` auto-detection | `scripts/_common.sh` | Sub-skills add a one-line note + pointer to the script's hard error |
| `.roundtable/` inside project root | `_common.sh` | Same — sub-skills reference, scripts enforce |
| Independent verification rule | `roles/_independence_rule.md` (single source) | Unchanged |
| Goal bridge (`get_goal`/`create_goal`) | `codex_turn.sh` executor addendum | Unchanged (script-level) |

**Real bug found (NOT fixing per task constraint):**
- `roundtable-review/SKILL.md` line 34 has a silent relaxation ("unless the user explicitly said 'go' or 'dispatch now'") of the root SKILL.md's hard confirmation rule. Two readings of the rule disagree. User decides which wins.

## 5. Self-check criteria for the refactor

- [ ] Root `SKILL.md` ≤ 70 lines.
- [ ] Each sub-skill 50–80 lines, with Use when / Why / Process / Stop when / Handoff.
- [ ] Frontmatter `description` on every SKILL.md fits the superpowers shape.
- [ ] No duplicate dispatch-confirmation prose; sub-skills cite root.
- [ ] README.md ≤ 90 lines, Chinese, ≤ 2 emoji total.
- [ ] All scripts still parse (`bash -n`).
- [ ] Every capability in §4 is reachable from the new structure.
