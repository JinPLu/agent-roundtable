#!/usr/bin/env bash
# Smoke-test H4 — roundtable-budget-gate.
# Verifies:
#   1. Non-matching command → {} allow.
#   2. Matching turn command with no ledger → {} allow (check_budget returns OK).
#   3. Matching turn command with ledger over .budget cap → deny exit 2.
#   4. Matching turn command but thread dir missing → {} allow.
#   5. Empty stdin → {} allow.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/roundtable-budget-gate.sh"
SKILL="$(cd "$HERE/.." && pwd)"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

mkdir -p "$tmp_root/.roundtable/threads/cheap-thread"
mkdir -p "$tmp_root/.roundtable/threads/broke-thread"

# Broke thread: 5x $0.10 estimates against a $0.20 cap → should fail.
cat > "$tmp_root/.roundtable/threads/broke-thread/.budget_ledger.jsonl" <<'EOF'
{"est_usd": 0.10, "ts": "2026-01-01T00:00:00Z"}
{"est_usd": 0.10, "ts": "2026-01-01T00:01:00Z"}
{"est_usd": 0.10, "ts": "2026-01-01T00:02:00Z"}
{"est_usd": 0.10, "ts": "2026-01-01T00:03:00Z"}
{"est_usd": 0.10, "ts": "2026-01-01T00:04:00Z"}
EOF
echo "0.20" > "$tmp_root/.roundtable/threads/broke-thread/.budget"

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

_assert "non-turn cmd"        0 "{}"   "ls -la"
_assert "cheap thread ok"     0 "{}"   "bash scripts/codex_turn.sh cheap-thread --role executor"
_assert "missing thread"      0 "{}"   "bash scripts/codex_turn.sh nonexistent --role executor"
_assert "over-budget blocks"  2 "deny" "bash scripts/codex_turn.sh broke-thread --role executor"
_assert "claude turn over budget" 2 "deny" "bash scripts/claude_turn.sh broke-thread --role executor"
_assert "empty stdin"         0 "{}"   ""

[[ "$fail" -eq 0 ]]
echo "H4 smoketest OK"
