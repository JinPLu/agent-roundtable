#!/usr/bin/env bash
# H3 — Surface oracle results after executor turns (postToolUse).
set -euo pipefail
if [[ "${ROUNDTABLE_HOOK_INTERNAL:-}" == "1" ]]; then
  printf '%s\n' '{}'
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
  echo "WARN [roundtable-oracle-post]: jq missing; fail-open" >&2
  printf '%s\n' '{}'
  exit 0
fi
_tool="$(echo "$input" | jq -r '.tool // .toolName // empty')"
[[ "$_tool" == "Shell" ]] || { printf '%s\n' '{}'; exit 0; }
_out="$(echo "$input" | jq -r '.output // .toolOutput // empty')"
echo "$_out" | grep -q "ROUNDTABLE_DONE:" || { printf '%s\n' '{}'; exit 0; }
echo "$_out" | grep -q "role=executor" || { printf '%s\n' '{}'; exit 0; }
_cmd="$(echo "$input" | jq -r '.command // .shellCommand // empty')"
_slug="$(echo "$_cmd" | sed -E 's/.*(codex_turn|claude_turn)\.sh[[:space:]]+([^[:space:]]+).*/\2/')"
_root="${ROUNDTABLE_PROJECT_ROOT:-}"
[[ -n "$_root" ]] || _root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
_thread="$_root/.roundtable/threads/$_slug"
[[ -d "$_thread" ]] || { printf '%s\n' '{}'; exit 0; }
_payload="$(ROUNDTABLE_HOOK_INTERNAL=1 python3 "$SKILL_DIR/scripts/lib/oracle_runner.py" \
  --project "$_root" --thread "$_slug" --event post_executor 2>/dev/null || true)"
[[ -n "$_payload" ]] || _payload='{}'
_ctx="$(echo "$_payload" | jq -c '{last_oracle: .}' 2>/dev/null || echo "{}")"
printf '{"additional_context":%s}\n' "$_ctx"
exit 0
