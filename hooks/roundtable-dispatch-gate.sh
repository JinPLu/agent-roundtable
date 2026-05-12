#!/usr/bin/env bash
# H1 — roundtable-dispatch-gate
#
# Cursor event:  beforeShellExecution
#                (mapped from Claude Code PreToolUse / matcher Bash)
# Matcher:       commands containing codex_turn.sh or claude_turn.sh
# failClosed:    false (hook crash → fall-through, do not block)
#
# Mechanises Hard Rule #2 (Dispatch confirmation): a turn script must not
# run unless the operator passed --force OR exported
# ROUNDTABLE_DISPATCH_CONFIRMED=1.  Until now this was enforced inside the
# turn scripts themselves; the hook catches it one layer earlier (parent
# tool-call layer) so even if parent shells out via a wrapper the gate
# still fires.
#
# Output (per https://cursor.com/docs/reference/third-party-hooks):
#   no match / bypass present → {}                               (allow)
#   matched + no bypass       → {"permission":"deny",...} exit 2 (block)

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
  echo "WARN [roundtable-dispatch-gate]: jq not found on PATH; fail-open" >&2
  echo '{}'
  exit 0
fi

input="$(cat)"
if [[ -z "$input" ]]; then
  echo '{}'
  exit 0
fi

# Cursor native sends .command; Claude Code PreToolUse sends
# .tool_input.command for Bash tool. Accept both.
command_str="$(echo "$input" | jq -r '.command // .tool_input.command // .shellCommand // empty' 2>/dev/null || echo "")"
if [[ -z "$command_str" ]]; then
  echo '{}'
  exit 0
fi

# Matcher: only act on codex_turn.sh / claude_turn.sh invocations.
if [[ "$command_str" != *codex_turn.sh* && "$command_str" != *claude_turn.sh* ]]; then
  echo '{}'
  exit 0
fi

# Bypass conditions: either env var set in the command line, or --force flag,
# or the variable already exported when the hook was invoked (Cursor passes
# the parent's env through).
if [[ "${ROUNDTABLE_DISPATCH_CONFIRMED:-0}" == "1" ]] \
   || [[ "${ROUNDTABLE_FORCE:-0}" == "1" ]] \
   || [[ "$command_str" == *"ROUNDTABLE_DISPATCH_CONFIRMED=1"* ]] \
   || [[ "$command_str" == *"--force"* ]]; then
  echo '{}'
  exit 0
fi

msg="Roundtable dispatch confirmation missing. Generate the block (python3 ${SKILL_DIR:-<SKILL>}/scripts/print_dispatch_block.py --model M --role R), get user approval, then export ROUNDTABLE_DISPATCH_CONFIRMED=1 (or pass --force for CI). See Hard Rule #2."
jq -nc --arg msg "$msg" '{
  permission: "deny",
  user_message: $msg,
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $msg
  }
}'
exit 2
