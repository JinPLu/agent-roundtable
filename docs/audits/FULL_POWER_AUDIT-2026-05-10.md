# Full-power capability audit — agent-roundtable

> Date: 2026-05-10
> Lens: does the skill let agent CLIs run at full power and fully explore the project?
> Method: read-only audit of every script, role, doc, and config.

## TL;DR

- **`ROUNDTABLE_PROJECT_ROOT` was prompt-only:** `emit_repo_context` listed `.planning/` paths but no script passed `ROUNDTABLE_PROJECT_ROOT` to `--add-dir`, so agents saw the paths but couldn't open them. **Fixed in commit `<see git log>`** — both `codex_turn.sh` and `claude_turn.sh` now mount it as an extra `--add-dir` when set and distinct from `repo_root`.
- **Default `ROUNDTABLE_REPO_ROOT` resolved to the skill's own git root** when run from inside the skill's scripts, instead of the user's project. **Fixed** — resolution now prefers caller's cwd over script-dir, with a loud WARN if it ends up pointing at the skill itself.
- **Reviewer / devils-advocate role prompts banned all network commands**, contradicting the skill's "full WebSearch/WebFetch" policy. **Fixed** — only state-mutating commands (`pip install`, etc.) are blocked; read-only network access (WebSearch, WebFetch, `curl GET`, `git fetch`) is now explicitly permitted.

## Findings by category

### A. Tool restrictions (per script)

| Location | Original | Status after fix |
|----------|----------|------------------|
| `scripts/codex_turn.sh` | `-s workspace-write`; `approval_policy=never`; no tool flags | Unchanged — already minimal. `--add-dir` now multi-valued. |
| `scripts/claude_turn.sh` reviewer/aggregator/devils-advocate | tight allowlist + `--disallowedTools "WebSearch WebFetch"` | No allowlist; no disallow. Plan mode handles writes. |
| `scripts/claude_turn.sh` other roles | disallowed git push/rebase/reset --hard/**fetch**/remote/config/filter-branch/update-ref/checkout origin/* + WebSearch/WebFetch | **Tightened to truly destructive only**: `push`, `push --force`, `rebase`, `reset --hard`, `filter-branch`, `update-ref`. fetch/remote/config/checkout-origin re-enabled for legitimate exploration. |
| `roles/reviewer.system.md` + `devils-advocate.system.md` | "Do not run network commands or installers." | Replaced with: read-only network tools permitted; only state-mutating system commands blocked. |

### B. Project exploration

1. `emit_repo_context` already enumerates `.planning/` files when `ROUNDTABLE_PROJECT_ROOT` is set — good bootstrap.
2. CLIs now also **mount** `ROUNDTABLE_PROJECT_ROOT` so the listed paths are openable. (Was the critical gap.)
3. Without `ROUNDTABLE_PROJECT_ROOT`, agents fall back to `repo_root` only. WARN when `repo_root == skill dir` makes the misconfig visible immediately.

### C. Context / timeout / truncation

Defaults are reasonable for most work; document escape hatches in SKILL.md:
- `ROUNDTABLE_TAIL_K` (default 3) — bump for tightly coupled debates.
- `--timeout-s 0` — disables wallclock cap entirely.
- Compaction strips `**Read**` and truncates `**Verification**` to 350-1000 chars; `THREAD.md` keeps the full record. Agents are told to read the full file when needed.

### D. Prompt content

`build_prompt` ordering: stable prefix → thread metadata → `GOAL.md` → repo + project context → earlier history → recent K turns → latest verdict (unless blind) → `OPEN_QUESTIONS.md` → role guidelines → addendum.

`_independence_rule.md` and Hard rule #1 explicitly say `THREAD.md` is a log, not evidence. Encourages exploration.

### E. Working directory

- **codex executor**: cwd=repo_root, --add-dir=[thread_dir, project_root if set+distinct]. Source writes allowed via cwd.
- **codex non-executor**: cwd=thread_dir, --add-dir=[repo_root, project_root if set+distinct]. Source read-only via add-dir.
- **claude all roles**: cwd=repo_root (or worktree), --add-dir=[thread_dir, project_root if set+distinct]. Permission-mode controls writes.

### F. Anti-patterns

- ✅ No "ask user before reading" anywhere mid-turn (only orchestrator confirms before dispatch — that's user-facing, not agent-facing).
- ✅ Hard rules are protocol/orchestration, not exploration limits.
- ✅ Output parsing: `extract_json_verdict` warns but doesn't reject; `verdict.json` may be absent on malformed output but the turn still appends.

## Top fixes (ordered by leverage) — all applied

1. ✅ **Mount `ROUNDTABLE_PROJECT_ROOT` as `--add-dir`** in both turn scripts.
2. ✅ **Reconcile reviewer/devils-advocate "no network" with full-tools policy** — read-only network permitted.
3. ✅ **Reverse `ROUNDTABLE_REPO_ROOT` priority** — caller's cwd wins over script-dir; warn if it resolves to the skill itself.
4. ✅ **Tighten claude `--disallowedTools`** to truly destructive ops only.
5. ⏳ **Optional**: explicit "you may read any path under mounted dirs" line in `build_prompt` — not done; existing prompt structure is already clear.

## Verified to be working well (don't change without cause)

- No reviewer Claude tool allowlist — plan mode is enough.
- Codex cwd + `--add-dir` pairing for executor vs non-executor.
- `emit_repo_context` `.planning/` enumeration.
- `build_prompt` ordering + "read THREAD.md for full history".
- `--timeout-s 0` escape hatch.
