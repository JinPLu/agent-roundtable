#!/usr/bin/env bash
# H4 — Budget gate before codex/claude turns.
set -euo pipefail
if [[ "${ROUNDTABLE_HOOK_INTERNAL:-}" == "1" ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
_resolve_skill_dir() {
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [[ "$d" != "/" ]]; do
    if [[ -f "$d/SKILL.md" ]]; then
      printf '%s\n' "$d"
      return 0
    fi
    d="$(dirname "$d")"
  done
  printf '%s\n' ""
}
SKILL_DIR="$(_resolve_skill_dir)"
input="$(cat)"
if ! command -v jq >/dev/null 2>&1; then
  echo "WARN [roundtable-budget-gate]: jq missing; fail-open" >&2
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
cmd="$(echo "$input" | jq -r '.command // .shellCommand // empty')"
if [[ ! "$cmd" =~ codex_turn\.sh ]] && [[ ! "$cmd" =~ claude_turn\.sh ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
_slug="$(echo "$cmd" | sed -E 's/.*(codex_turn|claude_turn)\.sh[[:space:]]+([^[:space:]]+).*/\2/')"
[[ -n "$_slug" ]] || { printf '%s\n' '{"permission":"allow"}'; exit 0; }
_root="${ROUNDTABLE_PROJECT_ROOT:-}"
[[ -n "$_root" ]] || _root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
_thread="$_root/.roundtable/threads/$_slug"
[[ -d "$_thread" ]] || { printf '%s\n' '{"permission":"allow"}'; exit 0; }
export ROUNDTABLE_HOOK_INTERNAL=1
if ! python3 "$SKILL_DIR/scripts/lib/check_budget.py" "$_thread" >/dev/null 2>&1; then
  _msg="$(python3 "$SKILL_DIR/scripts/lib/check_budget.py" "$_thread" 2>&1 | tail -3 | tr '"' "'")"
  printf '{"permission":"deny","agent_message":"[roundtable H4] Budget blocked: %s"}\n' "$_msg"
  exit 0
fi
printf '%s\n' '{"permission":"allow"}'
exit 0
