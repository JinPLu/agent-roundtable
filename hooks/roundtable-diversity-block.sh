#!/usr/bin/env bash
# H2 — roundtable-diversity-block
#
# Cursor event:  beforeShellExecution
#                (mapped from Claude Code PreToolUse / matcher Bash)
# Matcher:       commands containing --role reviewer-aggregator
# failClosed:    false (hook crash → fall-through, do not block)
#
# Mechanises Hard Rule #4 (Cross-vendor blind review): a
# reviewer-aggregator dispatch must not run until the last 2 reviewer
# turns come from different actor families (see check_review_diversity.py).
# Until now the check ran inside the turn script *after* gates passed and
# only emitted a warning (`|| true`).  This hook makes it a hard deny
# at the tool-call layer.

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
  echo "WARN [roundtable-diversity-block]: jq not found on PATH; fail-open" >&2
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

# Matcher: --role reviewer-aggregator (allow both `--role X` and `--role=X` forms).
if ! [[ "$command_str" =~ --role[[:space:]=]+reviewer-aggregator ]]; then
  echo '{}'
  exit 0
fi

# Extract slug — first positional after `(codex|claude)_turn.sh`.
slug=""
if [[ "$command_str" =~ (codex_turn\.sh|claude_turn\.sh)[[:space:]]+([^[:space:]]+) ]]; then
  slug="${BASH_REMATCH[2]}"
fi
if [[ -z "$slug" ]]; then
  echo "WARN [roundtable-diversity-block]: could not extract thread slug from command; fail-open" >&2
  echo '{}'
  exit 0
fi

project_root="${ROUNDTABLE_PROJECT_ROOT:-}"
if [[ -z "$project_root" ]]; then
  project_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
thread_dir="$project_root/.roundtable/threads/$slug"
if [[ ! -d "$thread_dir" ]]; then
  # Brand-new thread or stale slug — let the turn script handle it.
  echo '{}'
  exit 0
fi

checker="$SKILL_DIR/scripts/lib/check_review_diversity.py"
if [[ ! -f "$checker" ]]; then
  echo "WARN [roundtable-diversity-block]: check_review_diversity.py not found at $checker; fail-open" >&2
  echo '{}'
  exit 0
fi

_tmp="$(mktemp)"
trap 'rm -f "$_tmp"' EXIT
if python3 "$checker" "$thread_dir" >"$_tmp" 2>&1; then
  echo '{}'
  exit 0
fi
reason="$(cat "$_tmp" 2>/dev/null || echo "Same-vendor reviewer pair detected (Hard Rule #4 violation).")"

msg="Roundtable diversity gate: $reason"
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
