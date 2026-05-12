#!/usr/bin/env bash
# H3 — roundtable-oracle-post
#
# Cursor event:  postToolUse
#                (mapped from Claude Code PostToolUse / matcher Bash)
# Matcher:       Shell tool invocations of *executor* turn scripts
# failClosed:    false (this hook never blocks — it only injects context)
#
# After an executor turn finishes, run the project-local oracles (pytest
# / mypy / linters as configured in oracles.yaml) and surface results to
# the parent as additional_context so the next reviewer / planner / H5
# turn can see whether the executor's claim of "done" actually holds.
# postToolUse hooks have no permission verb — the only knob is
# additional_context.

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
  echo "WARN [roundtable-oracle-post]: jq not found on PATH; fail-open" >&2
  echo '{}'
  exit 0
fi

input="$(cat)"
if [[ -z "$input" ]]; then
  echo '{}'
  exit 0
fi

command_str="$(echo "$input" | jq -r '.command // .tool_input.command // .shellCommand // empty' 2>/dev/null || echo "")"
if [[ -z "$command_str" ]]; then
  echo '{}'
  exit 0
fi

# Only fire for executor turns. Reviewer/planner turns don't modify code,
# so oracles add no signal there.
if [[ "$command_str" != *codex_turn.sh* && "$command_str" != *claude_turn.sh* ]]; then
  echo '{}'
  exit 0
fi
if ! [[ "$command_str" =~ --role[[:space:]=]+executor ]]; then
  echo '{}'
  exit 0
fi

slug=""
if [[ "$command_str" =~ (codex_turn\.sh|claude_turn\.sh)[[:space:]]+([^[:space:]]+) ]]; then
  slug="${BASH_REMATCH[2]}"
fi
[[ -z "$slug" ]] && { echo '{}'; exit 0; }

project_root="${ROUNDTABLE_PROJECT_ROOT:-}"
if [[ -z "$project_root" ]]; then
  project_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
thread_dir="$project_root/.roundtable/threads/$slug"
if [[ ! -d "$thread_dir" ]]; then
  echo '{}'
  exit 0
fi

runner="$SKILL_DIR/scripts/lib/oracle_runner.py"
if [[ ! -f "$runner" ]]; then
  echo "WARN [roundtable-oracle-post]: oracle_runner.py not found; fail-open" >&2
  echo '{}'
  exit 0
fi

# Run oracles for the post_executor phase; runner writes
# <thread>/.roundtable/last_oracle.json which H5 reads.  We swallow any
# non-zero exit — additional_context still includes the message so the
# reviewer can see something failed.
summary=""
out="$(python3 "$runner" --project "$project_root" --thread "$slug" --event post_executor 2>&1 || true)"
summary="$(echo "$out" | tail -n 20 | tr '\n' ' ' | sed 's/  */ /g')"

if [[ -z "$summary" ]]; then
  echo '{}'
  exit 0
fi

ctx="Oracles ran after executor turn (thread=$slug): $summary"
jq -nc --arg ctx "$ctx" '{additional_context: $ctx}'
exit 0
