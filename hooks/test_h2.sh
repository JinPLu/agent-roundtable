#!/usr/bin/env bash
# Smoke-test H2 — roundtable-diversity-block.
# Verifies:
#   1. Non reviewer-aggregator command → {} allow.
#   2. reviewer-aggregator with no thread dir → {} allow (fall-through).
#   3. reviewer-aggregator with a thread that has same-vendor reviewers → deny.
#   4. reviewer-aggregator with a thread that has cross-vendor reviewers → {} allow.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/roundtable-diversity-block.sh"
SKILL="$(cd "$HERE/.." && pwd)"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

# Build a fake project with a thread containing same-vendor reviewers.
mk_thread() {
  local slug="$1" thread_md="$2"
  local td="$tmp_root/.roundtable/threads/$slug"
  mkdir -p "$td"
  printf '%s' "$thread_md" > "$td/THREAD.md"
}

mk_thread "same-vendor" \
'## Turn 1 — codex-gpt5 / reviewer — 2026-05-12
body
## Turn 2 — codex-gpt5-mini / reviewer — 2026-05-12
body
'

mk_thread "cross-vendor" \
'## Turn 1 — codex-gpt5 / reviewer — 2026-05-12
body
## Turn 2 — claude-opus / reviewer — 2026-05-12
body
'

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

_assert "non-reviewer-agg"   0 "{}"   "bash scripts/codex_turn.sh same-vendor --role executor"
_assert "missing thread"     0 "{}"   "bash scripts/codex_turn.sh nonexistent --role reviewer-aggregator"
_assert "same-vendor blocks" 2 "deny" "bash scripts/codex_turn.sh same-vendor --role reviewer-aggregator"
_assert "cross-vendor ok"    0 "{}"   "bash scripts/codex_turn.sh cross-vendor --role reviewer-aggregator"
_assert "equals form blocks" 2 "deny" "bash scripts/codex_turn.sh same-vendor --role=reviewer-aggregator"

[[ "$fail" -eq 0 ]]
echo "H2 smoketest OK"
