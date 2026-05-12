#!/usr/bin/env bash
# H5 — Autopilot continuation via stop hook + followup_message.
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
  echo "WARN [roundtable-autopilot-continue]: jq missing; fail-open" >&2
  printf '%s\n' '{}'
  exit 0
fi
_status="$(echo "$input" | jq -r '.status // empty')"
[[ "$_status" == "completed" ]] || { printf '%s\n' '{}'; exit 0; }
_loop="$(echo "$input" | jq -r '.loop_count // 0')"
_root="${ROUNDTABLE_PROJECT_ROOT:-}"
[[ -n "$_root" ]] || _root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
_threads="$_root/.roundtable/threads"
[[ -d "$_threads" ]] || { printf '%s\n' '{}'; exit 0; }

while IFS= read -r -d '' marker; do
  td="$(dirname "$marker")"
  [[ -f "$td/.autopilot.abort" ]] && { rm -f "$marker"; continue; }

  verdict=""
  if verdict="$(find "$td/history" -name verdict.json -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"; then
    :
  fi
  [[ -n "$verdict" && -f "$verdict" ]] || continue

  converged="$(jq -r '.convergence_status // empty' "$verdict" 2>/dev/null || true)"
  blockers="$(jq -r '[.blocking_issues[]? | select(.severity=="BLOCKER")] | length' "$verdict" 2>/dev/null || echo 999)"
  if [[ "$converged" == "converged" && "${blockers:-999}" == "0" ]]; then
    rm -f "$marker"
    continue
  fi

  export ROUNDTABLE_HOOK_INTERNAL=1
  if ! python3 "$SKILL_DIR/scripts/lib/check_budget.py" "$td" >/dev/null 2>&1; then
    rm -f "$marker"
    continue
  fi

  hint=""
  _oracle="$td/.roundtable/last_oracle.json"
  if [[ -f "$_oracle" ]]; then
    oracle_fail="$(jq -r '[.results[]? | select(.must_pass == true and .exit_code != 0)] | length' "$_oracle" 2>/dev/null || echo 0)"
    if [[ "${oracle_fail:-0}" -gt 0 ]]; then
      hint="ORACLE_FAIL fix failing must_pass oracles then re-execute executor"
    fi
  fi
  hint="${hint:-$(jq -r '.next_action_hint // "continue"' "$verdict" 2>/dev/null || echo continue)}"
  slug="$(basename "$td")"
  printf '{"followup_message":"/roundtable-goal autopilot continue: thread=%s loop_count=%s prefer_resume=1 next_action_hint=%s"}\n' \
    "$slug" "$_loop" "$hint"
  exit 0
done < <(find "$_threads" -maxdepth 2 -name .autopilot -print0 2>/dev/null)

printf '%s\n' '{}'
exit 0
