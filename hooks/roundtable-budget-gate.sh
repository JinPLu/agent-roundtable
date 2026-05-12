#!/usr/bin/env bash
# H4 — roundtable-budget-gate
#
# Cursor event:  beforeShellExecution
#                (mapped from Claude Code PreToolUse / matcher Bash)
# Matcher:       commands containing codex_turn.sh or claude_turn.sh
# failClosed:    false (hook crash → fall-through, do not block)
#
# Mechanises Hard Rule #5 (Budget cap): before firing a turn, run
# check_budget.py against the thread's .budget_ledger.jsonl.  exit != 0
# means accumulated USD has hit/exceeded the .budget cap → permission deny.
#
# Note: once CX2 ships, check_budget.py prefers real_usd over est_usd;
# this hook gets the upgrade for free (it shells out to the same module).

set -euo pipefail

if [[ "${ROUNDTABLE_HOOK_INTERNAL:-0}" == "1" ]]; then
  echo '{}'
  exit 0
fi
export ROUNDTABLE_HOOK_INTERNAL=1

SKILL_DIR=""
_probe="$(cd "$(dirname "$0")" && pwd)"
while [[ "$_probe" != "/" && "$_probe" != "" ]]; do
  if [[ -f "$_probe/SKILL.md" ]]; then
    SKILL_DIR="$_probe"
    break
  fi
  _probe="$(dirname "$_probe")"
done
export SKILL_DIR

if ! command -v jq >/dev/null 2>&1; then
  echo "WARN [roundtable-budget-gate]: jq not found on PATH; fail-open" >&2
  echo '{}'
  exit 0
fi

input="$(cat)"
if [[ -z "$input" ]]; then
  echo '{}'
  exit 0
fi

command_str="$(echo "$input" | jq -r '.command // .tool_input.command // .shellCommand // empty' 2>/dev/null || echo "")"
if [[ -z "$command_str" ]]; then
  echo '{}'
  exit 0
fi

if [[ "$command_str" != *codex_turn.sh* && "$command_str" != *claude_turn.sh* ]]; then
  echo '{}'
  exit 0
fi

slug=""
if [[ "$command_str" =~ (codex_turn\.sh|claude_turn\.sh)[[:space:]]+([^[:space:]]+) ]]; then
  slug="${BASH_REMATCH[2]}"
fi
[[ -z "$slug" ]] && { echo '{}'; exit 0; }

project_root="${ROUNDTABLE_PROJECT_ROOT:-}"
if [[ -z "$project_root" ]]; then
  project_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
thread_dir="$project_root/.roundtable/threads/$slug"
if [[ ! -d "$thread_dir" ]]; then
  echo '{}'
  exit 0
fi

checker="$SKILL_DIR/scripts/lib/check_budget.py"
if [[ ! -f "$checker" ]]; then
  echo "WARN [roundtable-budget-gate]: check_budget.py not found at $checker; fail-open" >&2
  echo '{}'
  exit 0
fi

if msg="$(python3 "$checker" "$thread_dir" 2>&1)"; then
  echo '{}'
  exit 0
fi

reason="${msg:-Budget cap reached for this thread (see .budget_ledger.jsonl).}"
deny="Roundtable budget gate: $reason"

jq -nc --arg msg "$deny" '{
  permission: "deny",
  user_message: $msg,
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $msg
  }
}'
exit 2
