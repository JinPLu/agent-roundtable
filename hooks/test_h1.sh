#!/usr/bin/env bash
# Smoke-test H1 — roundtable-dispatch-gate.
# Verifies:
#   1. Non-matching command → {} allow.
#   2. Matching command without bypass → permission deny (exit 2).
#   3. Matching command with --force → {} allow (exit 0).
#   4. Matching command with ROUNDTABLE_DISPATCH_CONFIRMED=1 in line → {} allow.
#   5. Empty stdin → {} allow.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/roundtable-dispatch-gate.sh"
fail=0

_assert() {
  local desc="$1" expected_exit="$2" expected_substr="$3" stdin="$4"
  set +e
  out="$(printf '%s' "$stdin" | env -i PATH="$PATH" HOME="$HOME" bash "$HOOK" 2>/dev/null)"
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

_assert "no match"        0 "{}"     '{"command":"ls -la"}'
_assert "match no bypass" 2 "deny"   '{"command":"bash scripts/codex_turn.sh my-thread --role executor"}'
_assert "match --force"   0 "{}"     '{"command":"bash scripts/codex_turn.sh my-thread --role executor --force"}'
_assert "match env in cmd" 0 "{}"    '{"command":"ROUNDTABLE_DISPATCH_CONFIRMED=1 bash scripts/claude_turn.sh t --role reviewer"}'
_assert "empty stdin"     0 "{}"     ''
_assert "claude turn no bypass" 2 "deny" '{"command":"bash scripts/claude_turn.sh foo --role planner"}'
_assert "nested tool_input form" 2 "deny" '{"tool_input":{"command":"bash scripts/codex_turn.sh foo --role planner"}}'

[[ "$fail" -eq 0 ]]
echo "H1 smoketest OK"
