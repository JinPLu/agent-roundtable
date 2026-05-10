#!/usr/bin/env bash
# claude_turn.sh — Run one Claude Code turn against an existing roundtable thread.
# Requires bash >= 4.0, git, claude (Claude Code CLI), python3 (or jq).
#
# Body is wrapped in a brace group so bash parses it fully before executing,
# preventing the streaming-parser race when a turn modifies this file in-place
# (e.g. an executor adding wrapper logic).
{
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/_common.sh"

_usage() {
  cat <<'EOF'
Usage: claude_turn.sh <slug> --role ROLE [options]

Required:
  <slug>            Thread slug (must already exist).
  --role ROLE       planner | executor | reviewer | reviewer-aggregator | devils-advocate | discussant

Options:
  -m, --model M     Model passed to claude (default: from models.json).
  --effort LEVEL    low | medium | high | xhigh | max (default: high).
  --task TEXT       Per-turn instruction appended to the prompt.
  --task-file FILE  Per-turn instruction read from file (use for long inputs).
  --blind           Suppress prior reviewer verdict — required for parallel reviewers.
  -h, --help        Print this help.

Environment:
  ROUNDTABLE_PROJECT_ROOT  Project root (default: caller's git toplevel).
  ROUNDTABLE_TIMEOUT_S     Wallclock cap in seconds, 0 disables (default: 1500).
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

# ── Argument parsing ─────────────────────────────────────────────────────────
slug="${1:?missing thread slug}"; shift
role=""; model=""; effort="high"; blind=0
task=""; task_file=""
timeout_s="${ROUNDTABLE_TIMEOUT_S:-1500}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) role="$2"; shift 2;;
    -m|--model) model="$2"; shift 2;;
    --effort) effort="$2"; shift 2;;
    --task) task="$2"; shift 2;;
    --task-file) task_file="$2"; shift 2;;
    --blind) blind=1; shift;;
    *) echo "unknown flag: $1 (try -h)" >&2; exit 2;;
  esac
done
[[ -z "$role" ]] && { echo "ERROR: --role required" >&2; exit 2; }

# Pre-flight: task-file must be readable BEFORE we touch anything else.
if [[ -n "$task_file" && ! -r "$task_file" ]]; then
  echo "ERROR [claude_turn.sh]: --task-file '$task_file' missing or unreadable." >&2
  echo "  If running inside Cursor's sandboxed Shell tool, use a workspace-visible path." >&2
  exit 2
fi

if [[ -z "$model" ]]; then
  eval "$( resolve_model claude "$role" "" "$effort" )"
fi

# Permission-mode: reviewer-likes + planner get plan (read-only); others get acceptEdits.
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate|planner) perm="plan";;
  *) perm="acceptEdits";;
esac

thread_dir="$(require_thread "$slug")"
ts_c="$(ts_compact_unique)"
repo_root="$ROUNDTABLE_REPO_ROOT"
_role_sys_key="$role"
[[ "$role" == "reviewer-aggregator" ]] && _role_sys_key="reviewer"
# devils-advocate has its own system prompt; no alias needed
role_sys="${SKILL_DIR}/roles/${_role_sys_key}.system.md"

# Load per-actor backend env override (e.g. point claude at DeepSeek's
# Anthropic-compat endpoint). Mirrors the VSCode/Cursor Claude Code plugin's
# `claudeCode.environmentVariables` mechanism for CLI use. Silent no-op if
# `.claude_env.local` is absent — caller's parent-shell env is then used.
if load_actor_env claude; then
  echo "INFO [claude_turn.sh]: loaded backend env override from ${SKILL_DIR}/.claude_env.local (ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-<unset>})" >&2
fi

if [[ "$role" == "executor" && -z "${GIT_AUTHOR_EMAIL:-}" && -z "${GIT_COMMITTER_EMAIL:-}" ]]; then
  if ! ( cd "$repo_root" && git config user.email >/dev/null 2>&1 ); then
    echo "WARN [claude_turn.sh]: no GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL exported and no repo user.email; commits by this turn will fail." >&2
  fi
fi

# ── Run one claude turn ──────────────────────────────────────────────────────
hist="${thread_dir}/history/claude/${ts_c}"
mkdir -p "$hist"

_cwd="$repo_root"

# Compose addendum from task / task-file.
_add="${hist}/addendum.md"
: > "$_add"
[[ -n "$task_file" ]] && cat "$task_file" >> "$_add"
[[ -n "$task" ]] && printf '\n%s\n' "$task" >> "$_add"
mapfile -t _warnings < <(warn_addendum_sanity "$_add" "claude_turn.sh")
# Role guidelines are sent via --append-system-prompt; skip the inline duplicate.
# Blind mode: suppress the prior verdict block to prevent modal adoption sycophancy
# (85.5% adoption rate when agents see prior verdicts, per arXiv 2605.00914).
_prompt="$(ROUNDTABLE_SKIP_ROLE_SYS=1 ROUNDTABLE_SKIP_LATEST_VERDICT="${blind}" build_prompt "$thread_dir" "$role" "$_add" "${hist}/prompt.md")"

# Build CLI args. Mount thread_dir + (when set and distinct) ROUNDTABLE_PROJECT_ROOT
# so agents can actually open project files (.planning/, source code, etc.).
_args=( -p --output-format json --permission-mode "$perm" --effort "$effort" --add-dir "$thread_dir" )
if [[ -n "${ROUNDTABLE_PROJECT_ROOT:-}" && "$ROUNDTABLE_PROJECT_ROOT" != "$_cwd" && "$ROUNDTABLE_PROJECT_ROOT" != "$thread_dir" ]]; then
  _args+=( --add-dir "$ROUNDTABLE_PROJECT_ROOT" )
fi
[[ -n "$model" ]] && _args+=( --model "$model" )
_sys_prompt=""
if [[ -n "${ROUNDTABLE_MODEL_ALIAS:-}" ]]; then
  _sys_prompt+=$(python3 - "${SKILL_DIR}/models.json" "$ROUNDTABLE_MODEL_ALIAS" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])).get("models", {}).get(sys.argv[2])
if m:
    print("## Your Model Identity")
    print(f"You are operating as **{sys.argv[2]}**.")
    if m.get("underlying"): print(f"- Underlying: {m['underlying']}")
    if m.get("capabilities"): print(f"- Capabilities: {m['capabilities']}")
    if m.get("best_for"): print(f"- Best for: {', '.join(m['best_for'])}")
    if m.get("pricing"): print(f"- Pricing: {m['pricing']}")
    print()
PY
)
fi
if [[ -f "$role_sys" ]]; then
  _sys_prompt+=$'

'$(cat "$role_sys")
fi
[[ -n "$_sys_prompt" ]] && _args+=( --append-system-prompt "$_sys_prompt" )

# Per-role tool surface — minimal disablement principle.
# Reviewer-likes + planner get write protection via --permission-mode plan; no allowlist.
# Executor / discussant: only destructive git operations are blocked.
_tools=()
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate|planner) : ;;
  *)
    _tools+=( --disallowedTools "Bash(git push:*) Bash(git push) Bash(git push --force:*) Bash(git rebase:*) Bash(git rebase) Bash(git reset --hard:*) Bash(git reset --hard) Bash(git filter-branch:*) Bash(git update-ref:*)" );;
esac

# Reviewer-likes: ask claude to vendor-validate the verdict against the JSON
# schema (--json-schema takes the schema content, not a file path).
# extract_json_verdict still runs as a regex fallback for defence in depth.
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate)
    _schema="${SKILL_DIR}/roles/reviewer.schema.json"
    if [[ -f "$_schema" ]] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$_schema" >/dev/null 2>&1; then
      _args+=( --json-schema "$(cat "$_schema")" )
    else
      echo "WARN [claude_turn.sh]: reviewer.schema.json missing or invalid JSON; skipping --json-schema." >&2
    fi
    ;;
esac

_start=$(date +%s)
set +e
if command -v timeout >/dev/null 2>&1 && [[ "$timeout_s" -gt 0 ]]; then
  ( cd "$_cwd" && timeout --signal=TERM --kill-after=10 "${timeout_s}" \
      claude "${_args[@]}" "$(cat "$_prompt")" "${_tools[@]}" ) \
    < /dev/null > "${hist}/last.json" 2>"${hist}/stderr.log"
else
  ( cd "$_cwd" && claude "${_args[@]}" "$(cat "$_prompt")" "${_tools[@]}" ) \
    < /dev/null > "${hist}/last.json" 2>"${hist}/stderr.log"
fi
_ec=$?
set -e
_dur=$(( $(date +%s) - _start ))
if [[ "$_ec" -eq 124 ]]; then
  echo "WARN [claude_turn.sh]: claude exceeded ${timeout_s}s; killed by timeout (exit 124)." >&2
fi

# Extract final assistant text from last.json into last.md.
if [[ -s "${hist}/last.json" ]]; then
  if command -v jq >/dev/null 2>&1; then
    jq -r '
      (.result // .messages[-1].content // empty)
      | if type == "array" then map(select(.type == "text") | .text) | join("\n")
        else . end
    ' "${hist}/last.json" > "${hist}/last.md" 2>/dev/null || true
  elif command -v python3 >/dev/null 2>&1; then
    python3 "${SKILL_DIR}/scripts/lib/extract_claude_result.py" \
      "${hist}/last.json" > "${hist}/last.md" 2>/dev/null || true
  fi
  [[ -s "${hist}/last.md" ]] || cp "${hist}/last.json" "${hist}/last.md"
fi

# Planner + plan mode cannot write artifacts/ — capture extracted stdout into thread artifacts for operators.
_plan_art=""
if [[ "$role" == "planner" && "$perm" == "plan" && -s "${hist}/last.md" ]]; then
  mkdir -p "${thread_dir}/artifacts"
  _plan_art="${thread_dir}/artifacts/plan-claude-${ts_c}.md"
  cp "${hist}/last.md" "${_plan_art}"
  echo "plan_artifact=${_plan_art}" >&2
fi

_ts=$(iso_now)
_turn_n=""
if [[ -s "${hist}/last.md" ]]; then
  _turn_n="$(append_turn_md "${thread_dir}/THREAD.md" "claude" "$role" "$_ts" "${hist}/last.md")"
  echo "appended_turn=${_turn_n}"
else
  echo "WARNING: empty result; check ${hist}/stderr.log and last.json" >&2
fi

if [[ ( "$role" == "reviewer" || "$role" == "reviewer-aggregator" || "$role" == "devils-advocate" ) && -s "${hist}/last.md" ]]; then
  extract_json_verdict "${hist}/last.md" "${hist}/verdict.json" "claude/${ts_c}"
fi

write_meta "${hist}/meta.json" "claude" "${model:-default}" "$effort" "$role" "$perm" "$_ec" "$_dur" "$hist" "${ANTHROPIC_BASE_URL:-unset}" "${_warnings[@]}"

if [[ "$blind" -eq 1 ]]; then
  python3 - "${hist}/meta.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
d = json.loads(p.read_text())
d['blind'] = True
p.write_text(json.dumps(d, indent=2))
PY
fi

# Append project-wide usage record (best-effort; never alter exit status).
# See scripts/lib/log_turn_usage.py and docs/research/COST_ESTIMATION-2026-05-10.md §6.4.
python3 "${SKILL_DIR}/scripts/lib/log_turn_usage.py" \
  --actor claude \
  --thread "$slug" \
  --model "${model:-default}" \
  --role "$role" \
  --effort "$effort" \
  --exit-code "$_ec" \
  --elapsed-s "$_dur" \
  --source-file "${hist}/last.json" \
  >/dev/null 2>>"${hist}/stderr.log" || \
  echo "WARN [claude_turn.sh]: usage log append failed (non-fatal)" >&2

echo "history=${hist}"
echo "exit_code=${_ec}"
echo "duration_s=${_dur}"
emit_done "$thread_dir" "$hist" "claude" "$role" "$_ec" "$_turn_n" "$_dur"
exit $_ec
}
