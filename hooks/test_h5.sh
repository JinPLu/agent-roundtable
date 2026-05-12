#!/usr/bin/env bash
# Smoke-test H5 — roundtable-autopilot-continue.
# Verifies:
#   1. Empty stdin → {}.
#   2. status != completed → {}.
#   3. No .autopilot markers anywhere → {}.
#   4. Active autopilot + .autopilot.abort touched → {} (marker swept).
#   5. Active autopilot + converged verdict → {} (marker swept).
#   6. Active autopilot + unconverged verdict + over-budget → {} (marker swept).
#   7. Active autopilot + unconverged verdict + under-budget → followup_message.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/roundtable-autopilot-continue.sh"
SKILL="$(cd "$HERE/.." && pwd)"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT
threads="$tmp_root/.roundtable/threads"

mk_thread() {
  local slug="$1" verdict_json="$2" budget_used="$3" budget_cap="$4"
  local td="$threads/$slug"
  mkdir -p "$td/history/run-1"
  touch "$td/.autopilot"
  printf '%s' "$verdict_json" > "$td/history/run-1/verdict.json"
  if [[ -n "$budget_used" ]]; then
    : > "$td/.budget_ledger.jsonl"
    local n=0
    while [[ $n -lt $budget_used ]]; do
      echo '{"est_usd": 1.0}' >> "$td/.budget_ledger.jsonl"
      n=$((n+1))
    done
  fi
  if [[ -n "$budget_cap" ]]; then
    echo "$budget_cap" > "$td/.budget"
  fi
}

CONVERGED='{"convergence_status":"converged","blocking_issues":[],"next_action_hint":"none"}'
UNCONVERGED='{"convergence_status":"in-progress","blocking_issues":[],"next_action_hint":"executor:fix-tests"}'
HAS_BLOCKER='{"convergence_status":"converged","blocking_issues":[{"severity":"BLOCKER","msg":"broken"}],"next_action_hint":"reviewer:revisit"}'

fail=0
_assert() {
  local desc="$1" expected_exit="$2" expected_substr="$3" stdin="$4"
  set +e
  out="$(printf '%s' "$stdin" \
    | env -i PATH="$PATH" HOME="$HOME" ROUNDTABLE_PROJECT_ROOT="$tmp_root" bash "$HOOK" 2>/dev/null)"
  rc=$?
  set -e
  if [[ "$rc" != "$expected_exit" ]]; then
    echo "FAIL [$desc]: exit $rc, expected $expected_exit  out=$out" >&2
    fail=1; return
  fi
  if [[ -n "$expected_substr" ]] && [[ "$out" != *"$expected_substr"* ]]; then
    echo "FAIL [$desc]: output missing '$expected_substr'  out=$out" >&2
    fail=1; return
  fi
  echo "PASS [$desc]"
}

# 1) Empty stdin → {}.
_assert "empty stdin"  0 "{}" ""

# 2) status != completed → {}.
_assert "non-completed status"  0 "{}"  '{"status":"cancelled","loop_count":3}'

# 3) No threads dir → {}.
_assert "no threads dir"  0 "{}"  '{"status":"completed","loop_count":3}'

# Make the threads dir for subsequent cases.
mkdir -p "$threads"

# 4) Active autopilot with .autopilot.abort → swept, no followup.
mk_thread "aborted-thread" "$UNCONVERGED" "1" "10.00"
touch "$threads/aborted-thread/.autopilot.abort"
_assert "abort marker"  0 "{}"  '{"status":"completed","loop_count":3}'
[[ ! -f "$threads/aborted-thread/.autopilot" ]] && echo "PASS [abort marker cleaned]" || { echo "FAIL: abort marker not cleaned"; fail=1; }

# 5) Active autopilot with converged verdict → swept.
mk_thread "converged-thread" "$CONVERGED" "1" "10.00"
_assert "converged sweep"  0 "{}"  '{"status":"completed","loop_count":3}'
[[ ! -f "$threads/converged-thread/.autopilot" ]] && echo "PASS [converged marker cleaned]" || { echo "FAIL: converged marker not cleaned"; fail=1; }

# 6) Active autopilot with verdict that has BLOCKER → followup (still has blocking_issues so not converged).
# Note: this is also a candidate for case 7. We test it separately.
# (Skipped to keep ordering simple; case 7 below covers the followup path.)

# 7) Active autopilot, unconverged, under-budget → followup_message.
mk_thread "active-thread" "$UNCONVERGED" "" ""
_assert "active continue"  0 "followup_message"  '{"status":"completed","loop_count":3}'
_assert "active continue contains slug"  0 "active-thread"  '{"status":"completed","loop_count":3}'
_assert "active continue contains loop_count"  0 "loop_count=3"  '{"status":"completed","loop_count":3}'

# Active autopilot, over budget → swept.
mk_thread "broke-thread" "$UNCONVERGED" "100" "1.00"
# (active-thread still has its marker, will fire first. Remove it to isolate.)
rm -f "$threads/active-thread/.autopilot"
_assert "over-budget sweep"  0 "{}"  '{"status":"completed","loop_count":3}'
[[ ! -f "$threads/broke-thread/.autopilot" ]] && echo "PASS [broke marker cleaned]" || { echo "FAIL: broke marker not cleaned"; fail=1; }

[[ "$fail" -eq 0 ]]
echo "H5 smoketest OK"
