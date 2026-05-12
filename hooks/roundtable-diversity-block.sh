#!/usr/bin/env bash
# H2 — Cross-vendor reviewer diversity hard block before aggregator runs.
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
  echo "WARN [roundtable-diversity-block]: jq missing; fail-open" >&2
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
cmd="$(echo "$input" | jq -r '.command // .shellCommand // empty')"
if [[ ! "$cmd" =~ reviewer-aggregator ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
if ! echo "$cmd" | grep -qE '(codex_turn|claude_turn)\.sh'; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
_slug="$(echo "$cmd" | sed -E 's/.*(codex_turn|claude_turn)\.sh[[:space:]]+([^[:space:]]+).*/\2/')"
if [[ -z "$_slug" || "$_slug" == *".sh"* ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
_root="${ROUNDTABLE_PROJECT_ROOT:-}"
if [[ -z "$_root" ]]; then
  _root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
_thread="$_root/.roundtable/threads/$_slug"
if [[ ! -d "$_thread" ]]; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi
export ROUNDTABLE_HOOK_INTERNAL=1
set +e
_out="$(python3 "$SKILL_DIR/scripts/lib/check_review_diversity.py" "$_thread" 2>&1)"
_ec=$?
set -e
if [[ "$_ec" -eq 2 ]]; then
  _msg="$(echo "$_out" | tail -5 | tr '"' "'")"
  printf '{"permission":"deny","agent_message":"[roundtable H2] %s"}\n' "$_msg"
  exit 0
fi
printf '%s\n' '{"permission":"allow"}'
exit 0
