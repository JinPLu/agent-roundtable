#!/usr/bin/env bash
# H5 — roundtable-autopilot-continue
#
# Cursor event:  stop  (Claude Code event: Stop)
# Matcher:       n/a (fires on every stop; we filter inside)
# failClosed:    false (errors fall through to {}, do not block)
#
# Reads JSON from stdin describing the stopped session, scans
# .roundtable/threads/*/.autopilot markers, and — if an active autopilot
# thread is unconverged and under budget — emits a followup_message that
# tells parent /roundtable-goal to continue the convergence loop.
#
# Five safety gates (see plan §三 H5 5 重安全闸):
#   1. Cursor-layer loop_limit: 15 (set in hooks.json / settings.json)
#   2. .autopilot marker present (created by Phase 0 GO)
#   3. .autopilot.abort flag absent (touched by user to emergency-stop)
#   4. verdict.json convergence_status != "converged" or has BLOCKERs
#   5. check_budget.py exit==0 (under budget)

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
  echo "WARN [roundtable-autopilot-continue]: jq not found on PATH; fail-open" >&2
  echo '{}'
  exit 0
fi

input="$(cat)"
if [[ -z "$input" ]]; then
  echo '{}'
  exit 0
fi

loop_count="$(echo "$input" | jq -r '.loop_count // 0' 2>/dev/null || echo 0)"
status="$(echo "$input" | jq -r '.status // empty' 2>/dev/null || echo "")"

# Only fire on completed stops (not on errored / cancelled).
if [[ -n "$status" && "$status" != "completed" ]]; then
  echo '{}'
  exit 0
fi

project_root="${ROUNDTABLE_PROJECT_ROOT:-}"
if [[ -z "$project_root" ]]; then
  project_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
threads_root="$project_root/.roundtable/threads"
if [[ ! -d "$threads_root" ]]; then
  echo '{}'
  exit 0
fi

# Use find with -print0 + read -d '' so paths with spaces are safe.
while IFS= read -r -d '' marker; do
  td="$(dirname "$marker")"
  slug="$(basename "$td")"

  # Gate #3: emergency abort
  if [[ -f "$td/.autopilot.abort" ]]; then
    rm -f "$marker"
    continue
  fi

  # Find latest verdict.json under history/
  verdict=""
  if [[ -d "$td/history" ]]; then
    verdict="$(find "$td/history" -name verdict.json -printf '%T@ %p\n' 2>/dev/null \
              | sort -n | tail -1 | cut -d' ' -f2-)"
  fi
  [[ -z "$verdict" || ! -f "$verdict" ]] && continue

  converged="$(jq -r '.convergence_status // empty' "$verdict" 2>/dev/null || echo "")"
  blockers="$(jq -r '[.blocking_issues[]? | select(.severity=="BLOCKER")] | length' "$verdict" 2>/dev/null || echo 0)"

  # Gate #4: convergence detection
  if [[ "$converged" == "converged" && "$blockers" == "0" ]]; then
    rm -f "$marker"
    continue
  fi

  # Gate #5: budget detection
  if [[ -f "$SKILL_DIR/scripts/lib/check_budget.py" ]]; then
    if ! python3 "$SKILL_DIR/scripts/lib/check_budget.py" "$td" >/dev/null 2>&1; then
      rm -f "$marker"
      continue
    fi
  fi

  # Optional oracle-fail hint
  hint=""
  if [[ -f "$td/.roundtable/last_oracle.json" ]]; then
    oracle_fail="$(jq -r '[.results[]? | select(.must_pass == true and .exit_code != 0)] | length' \
                  "$td/.roundtable/last_oracle.json" 2>/dev/null || echo 0)"
    if [[ "$oracle_fail" -gt 0 ]]; then
      hint="ORACLE FAIL — fix and re-execute"
    fi
  fi
  if [[ -z "$hint" ]]; then
    hint="$(jq -r '.next_action_hint // "continue"' "$verdict" 2>/dev/null || echo continue)"
  fi

  # Emit followup_message and exit.  We only continue one thread per stop
  # event — if there are multiple active autopilots, the next will fire
  # on the next stop.
  jq -nc \
    --arg slug "$slug" \
    --arg loop "$loop_count" \
    --arg hint "$hint" \
    '{followup_message: "/roundtable-goal autopilot continue: thread=\($slug) loop_count=\($loop) next_action_hint=\($hint) prefer_resume=1"}'
  exit 0
done < <(find "$threads_root" -maxdepth 2 -name .autopilot -print0 2>/dev/null)

echo '{}'
exit 0
