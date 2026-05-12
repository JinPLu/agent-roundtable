#!/usr/bin/env bash
# Smoke-test H3 — roundtable-oracle-post.
# H3 never denies; only role we test for is "does it inject
# additional_context on executor turns and stay silent otherwise".
#
# Since oracle_runner.py needs a real thread + oracles.yaml setup we use
# a minimal stub: an empty thread dir + a fake runner injected via
# overriding SKILL_DIR's runner location is overkill — instead we just
# assert the hook short-circuits cleanly when oracles.yaml is absent (the
# real runner returns no-op summary) AND when the command doesn't match.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/roundtable-oracle-post.sh"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT
mkdir -p "$tmp_root/.roundtable/threads/some-thread"

fail=0
_assert() {
  local desc="$1" expected_exit="$2" expected_substr="$3" cmd="$4"
  set +e
  out="$(printf '{"command":%s}' "$(printf '%s' "$cmd" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
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

# 1) Not a turn command at all → {}.
_assert "non-turn cmd"      0 "{}" "ls -la"
# 2) Turn command but not executor role → {}.
_assert "reviewer turn"     0 "{}" "bash scripts/codex_turn.sh some-thread --role reviewer"
# 3) Executor turn but thread dir missing → {}.
_assert "missing thread"    0 "{}" "bash scripts/codex_turn.sh missing --role executor"
# 4) Executor turn with thread present → injects additional_context (oracles.yaml absent so it'll be a "no oracles configured" style line).
_assert "executor matches"  0 "additional_context" "bash scripts/codex_turn.sh some-thread --role executor"
# 5) Empty stdin → {}.
_assert "empty stdin"       0 "{}" ""

[[ "$fail" -eq 0 ]]
echo "H3 smoketest OK"
