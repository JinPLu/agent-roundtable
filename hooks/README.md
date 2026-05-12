# agent-roundtable Cursor hooks

Five Cursor hooks that mechanise existing agent-roundtable Hard Rules at the
**parent tool-call layer**, plus an autopilot continuation engine for
`/roundtable-goal`.  Until these hooks ship, the same constraints lived as
text in `SKILL.md` plus best-effort env checks inside `codex_turn.sh` /
`claude_turn.sh`; the hooks make them mechanical so a parent that skipped
the docs (or shelled out via a wrapper) is still caught.

See the plan at `/root/.cursor/plans/agent-roundtable_hook_5_件套_*.plan.md`
sections **三** (hook layer) and **四** (codex deep integration) for full
context.

## Hook matrix

| ID | Event | Matcher | failClosed | Behaviour |
|----|-------|---------|------------|-----------|
| **H1** | `beforeShellExecution` (Claude: `PreToolUse` / `Bash`) | `command =~ (codex\|claude)_turn\.sh` | false | Missing `ROUNDTABLE_DISPATCH_CONFIRMED=1` and no `--force` → `permission: deny` |
| **H2** | `beforeShellExecution` (Claude: `PreToolUse` / `Bash`) | `command =~ --role[ =]reviewer-aggregator` | false | `check_review_diversity.py` exit != 0 → `permission: deny` |
| **H3** | `postToolUse`        (Claude: `PostToolUse` / `Bash`) | executor-turn commands | false | Runs `oracle_runner.py`; injects result via `additional_context` (no deny) |
| **H4** | `beforeShellExecution` (Claude: `PreToolUse` / `Bash`) | `command =~ (codex\|claude)_turn\.sh` | false | `check_budget.py` exit != 0 → `permission: deny` |
| **H5** | `stop`               (Claude: `Stop`)                 | n/a (`loop_limit: 15`) | false | Autopilot continuation — emits `followup_message` when active thread is under budget and not converged |

All five hooks have `failClosed: false`: a crashed / missing-`jq` hook
returns `{}` and lets the action proceed.  Defence in depth is provided by
the existing in-script checks (`check_dispatch_confirmed`,
`check_review_diversity.py`, `check_budget.py`, `scope_check.py`).  See
plan §三 "为什么都 failClosed=false".

## Common script conventions

Each of the five `.sh` files follows the same skeleton:

- `#!/usr/bin/env bash` shebang and `set -euo pipefail`.
- **Recursion guard**: if `ROUNDTABLE_HOOK_INTERNAL=1` is already set the
  hook emits `{}` and exits 0 immediately.  Otherwise it exports it
  before doing any work, so anything the hook shells out to (`python3`,
  `find`, …) can't loop back through the same hook.
- **`SKILL_DIR` resolution**: walk up from `$(dirname "$0")` until a
  directory containing `SKILL.md` is found.  Means the hook works
  regardless of where the skill is installed (Cursor third-party-skills
  staging area, user-vendored path, etc.) — no `<SKILL_DIR>` substitution
  at runtime needed.
- **`jq` fallback**: `command -v jq` check; if missing, the hook prints a
  WARN to stderr and emits `{}` (fail-open).  Cursor's Hooks output
  channel surfaces the WARN so the operator can install jq.

## Input / output schema

### `beforeShellExecution` / `PreToolUse` (H1, H2, H4)

Input on stdin (Cursor native shown; Claude Code adds a `tool_input.command`
wrapper — both keys are handled):

```json
{
  "command": "bash scripts/codex_turn.sh my-thread --role executor",
  "cwd": "/path/to/project"
}
```

Allow output:

```json
{}
```

Deny output (exit code 2):

```json
{
  "permission": "deny",
  "user_message": "Roundtable dispatch confirmation missing. ...",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Roundtable dispatch confirmation missing. ..."
  }
}
```

Both flat (Cursor native) and nested (Claude Code) response keys are
emitted simultaneously so the hook behaves identically under either
interpreter — see [Cursor third-party hooks docs §Response Format Compatibility](https://cursor.com/docs/reference/third-party-hooks#response-format-compatibility).

### `postToolUse` / `PostToolUse` (H3)

Input on stdin: same `.command` plus tool-result fields.

Output: either `{}` or

```json
{ "additional_context": "Oracles ran after executor turn (thread=foo): ..." }
```

`postToolUse` hooks have no `permission` verb — the only knob is
`additional_context`, which is appended to the parent agent's context so
the next planner/reviewer/H5 turn can see whether the executor's claim
holds up against the project oracles.

### `stop` / `Stop` (H5)

Input on stdin:

```json
{
  "status": "completed",
  "loop_count": 3
}
```

Continue-autopilot output:

```json
{
  "followup_message": "/roundtable-goal autopilot continue: thread=<slug> loop_count=<n> next_action_hint=<hint> prefer_resume=1"
}
```

No-continue output: `{}`.

H5 only emits `followup_message` when **all five** of these conditions
hold simultaneously:

1. Cursor-layer `loop_limit: 15` not yet reached (configured in
   `templates/hooks.json.tmpl`).
2. `<thread>/.autopilot` marker file exists (created by `/roundtable-goal`
   Phase 0 GO; deleted by H5 itself once the thread converges, busts
   budget, or aborts).
3. `<thread>/.autopilot.abort` does **not** exist (emergency stop — user
   can `touch` this file to halt instantly).
4. The latest `verdict.json` under `history/` has
   `convergence_status != "converged"` or has at least one
   `blocking_issues[].severity == "BLOCKER"`.
5. `check_budget.py <thread>` exits 0 (under budget cap).

If oracles ran (via H3) and `<thread>/.roundtable/last_oracle.json`
contains a `must_pass` oracle with a non-zero `exit_code`, the hint
becomes `"ORACLE FAIL — fix and re-execute"`; otherwise it falls back to
`verdict.json.next_action_hint`.

## failClosed semantics

For all hooks `failClosed: false` (in plan terms).  Concretely:

- Missing `jq` → WARN + `{}` (allow).
- Missing `SKILL.md` upward in tree (can't resolve `SKILL_DIR`) → still
  proceed where possible; subsequent shell-outs to `python3 $SKILL_DIR/...`
  will themselves fall through with a WARN.
- Empty stdin → `{}` (allow).
- Unmatched command (not a turn script) → `{}` (allow, transparent).
- Internal exception inside a shell-out (oracle runner crash, etc.) → WARN
  + `{}` (allow).  We trust the in-script defence (H1's
  `check_dispatch_confirmed`, H2's `check_review_diversity.py`,
  H4's `check_budget.py`, scope_check.py end-of-turn) to backstop.

A `permission: deny` exit only happens when the hook **succeeds** in
determining a deny condition exists.  Any other state defaults to allow.

## Installation

Two distribution channels, see plan §三 "Hook 双分发":

- **Cursor native** (`~/.cursor/hooks.json`): run
  `bash $SKILL/scripts/install_hooks.sh`.  Idempotent merge — repeated
  installs are a no-op; preserves the user's existing hooks; identifies
  roundtable entries by `_roundtable_id` prefix `roundtable.`.  Add
  `--uninstall` to remove cleanly, `--target <path>` to point elsewhere,
  `--dry-run` to preview.
- **Project-bundled via Cursor third-party skills**: the repo's
  `.claude/settings.json` already has the five entries with `<SKILL_DIR>`
  placeholders; `roundtable-setup` step 4b runs `sed` to replace
  `<SKILL_DIR>` with the absolute install path and backs up the original
  to `<dest>.roundtable-bak`.  Requires the user to enable Cursor
  Settings → Features → Third-party skills.

## Testing

Five bash smoke tests live alongside the hooks (`test_h1.sh` …
`test_h5.sh`).  Each tests the matcher-fires path and at least one
fail-open / no-match path by piping a synthetic JSON stdin and asserting
the JSON output + exit code.  Run them with:

```bash
for t in hooks/test_h*.sh; do bash "$t" || exit 1; done
```

Python tests for the installer live at
`scripts/lib/test_install_hooks.py` (fresh install, preserve existing,
idempotent re-install, uninstall, dry-run, smoketest, drop-empty-events,
replace-stale-entry).  Run with:

```bash
python3 -m pytest scripts/lib/test_install_hooks.py -v
```
