# agent-roundtable Cursor hooks

These scripts mechanicaly enforce Hard Rules at the Cursor shell/tool layer.

| ID | Script | Event | Matcher (regex) | Output |
|----|--------|-------|-----------------|--------|
| H1 | `roundtable-dispatch-gate.sh` | `beforeShellExecution` | `(codex|claude)_turn\.sh` | `permission` allow/deny |
| H2 | `roundtable-diversity-block.sh` | `beforeShellExecution` | `reviewer-aggregator` | allow/deny if same-vendor reviewers |
| H3 | `roundtable-oracle-post.sh` | `postToolUse` | `Shell` | `additional_context` with last oracle payload |
| H4 | `roundtable-budget-gate.sh` | `beforeShellExecution` | `(codex|claude)_turn\.sh` | allow/deny via `check_budget.py` |
| H5 | `roundtable-autopilot-continue.sh` | `stop` | n/a (`loop_limit: 15`) | `followup_message` for `/roundtable-goal` autopilot |

All hooks use **`failClosed: false`** at the Cursor level: if `jq` is missing or the script errors, they fail-open and log a WARN. In-thread checks in `codex_turn.sh` / `claude_turn.sh` remain the backstop.

## Install (native)

```bash
bash scripts/install_hooks.sh
bash scripts/install_hooks.sh --uninstall
```

## Bundled path

`<SKILL_DIR>` entries are also embedded in `.claude/settings.json` under Cursor-style hook keys so **Third-party hooks** can load them after `roundtable-setup` replaces `<SKILL_DIR>` with an absolute path.

## Environment

- `ROUNDTABLE_DISPATCH_CONFIRMED=1` — required for turns unless `--force` (duplicates script gate).
- `ROUNDTABLE_HOOK_INTERNAL=1` — set by hooks when calling Python helpers to avoid recursion.
