#!/usr/bin/env bash
# H1 — Dispatch confirmation gate (beforeShellExecution).
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
  echo "WARN [roundtable-dispatch-gate]: jq missing; fail-open" >&2
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
cmd="$(echo "$input" | jq -r '.command // .shellCommand // empty')"
if [[ ! "$cmd" =~ codex_turn\.sh ]] && [[ ! "$cmd" =~ claude_turn\.sh ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
if echo "$cmd" | grep -qE '(^|[;&|\s])(ROUNDTABLE_DISPATCH_CONFIRMED=1|export ROUNDTABLE_DISPATCH_CONFIRMED=1)' \
   || echo "$cmd" | grep -qE '(^|[;&|\s])--force\b' \
   || [[ "${ROUNDTABLE_DISPATCH_CONFIRMED:-0}" == "1" ]] \
   || [[ "${ROUNDTABLE_FORCE:-0}" == "1" ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
printf '%s\n' '{"permission":"deny","agent_message":"[roundtable H1] Dispatch not confirmed. Export ROUNDTABLE_DISPATCH_CONFIRMED=1 after AskQuestion(go), or pass --force for CI."}'
exit 0
