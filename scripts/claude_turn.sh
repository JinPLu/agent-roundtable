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
timeout_s="${ROUNDTABLE_TIMEOUT_S:-3600}"
idle_s="${ROUNDTABLE_IDLE_S:-180}"
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

# Permission-mode (per Anthropic headless / dontAsk research, 2026-05-11):
# - reviewer-likes + planner -> plan (read-only)
# - executor / executor-fast -> dontAsk (only allow-listed tools run; rest are
#   denied without prompt). headless `claude -p` cannot answer permission
#   prompts, so default / acceptEdits effectively deny most Bash. dontAsk is
#   the documented CI / autonomous-agent pattern: explicit allow + explicit
#   deny, no interactive fallback.
# - other roles (discussant, researcher, researcher-deep) -> acceptEdits as
#   a sensible middle ground for now (mostly file-read + light writes).
# Allow/deny lists live in $cwd/.claude/settings.json (NOT under --add-dir;
# Anthropic docs: --add-dir paths do not contribute settings/hooks).
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate|planner) perm="plan";;
  executor|executor-fast|executor-heavy)               perm="dontAsk";;
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

# Exported for project-level hooks (templates/.claude/settings.json):
# - PostToolUse(Write|Edit) appends events to $ROUNDTABLE_HIST_DIR/edits.log
# - Stop writes the structured completion event to $ROUNDTABLE_HIST_DIR/stop.json
# Outside of roundtable dispatch the hooks no-op silently.
export ROUNDTABLE_HIST_DIR="$hist"

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
# Use stream-json so an idle_watchdog can monitor stream.jsonl progress and
# distinguish "thinking long" from "stuck" (per request 2026-05-11). The
# final {"type":"result", ...} event has the same shape as the old
# --output-format json blob — extract by tailing for it post-run.
_args=( -p --output-format stream-json --include-partial-messages --verbose --permission-mode "$perm" --effort "$effort" --add-dir "$thread_dir" )

# Per-turn firewall: cap in-turn $/iteration spend so a runaway loop cannot
# burn the whole roundtable budget (the roundtable parent budget is at
# round granularity, not turn-internal). Defaults are env-overridable;
# unset / empty values disable the corresponding flag.
_max_budget_usd="${ROUNDTABLE_CLAUDE_MAX_BUDGET_USD-10}"
_max_turns="${ROUNDTABLE_CLAUDE_MAX_TURNS-80}"
if [[ -n "$_max_budget_usd" ]]; then
  if claude --help 2>/dev/null | grep -q -- '--max-budget-usd'; then
    _args+=( --max-budget-usd "$_max_budget_usd" )
  else
    echo "WARN [claude_turn.sh]: claude --max-budget-usd not supported by installed CLI; skipping firewall." >&2
  fi
fi
if [[ -n "$_max_turns" ]]; then
  if claude --help 2>/dev/null | grep -q -- '--max-turns'; then
    _args+=( --max-turns "$_max_turns" )
  else
    echo "WARN [claude_turn.sh]: claude --max-turns not supported by installed CLI (need v2.x with this flag); skipping turn-count firewall." >&2
  fi
fi
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

# Per-role tool surface — settings.json is the source of truth.
#
# Permission allow/deny rules live in <project_cwd>/.claude/settings.json.
# Anthropic docs: --add-dir does NOT contribute settings, so the file MUST
# exist at the cwd claude is invoked from. roundtable-setup copies the
# template there; skill repo also ships its own .claude/settings.json so
# audits run against the skill itself work.
#
# We do NOT pass --disallowedTools as inline fallback anymore:
#   - executor / dontAsk: needs explicit allow rules (.claude/settings.json
#     permissions.allow); inline disallowedTools cannot grant Bash, only deny.
#   - reviewer-likes / plan: --permission-mode plan locks reads anyway.
#   - other roles / acceptEdits: settings.json deny rules still apply.
# If the cwd is missing .claude/settings.json the executor's dontAsk run will
# refuse most Bash; surface that loudly so users run roundtable-setup.
_tools=()
_proj_claude_settings="${_cwd}/.claude/settings.json"
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate|planner) : ;;
  executor|executor-fast|executor-heavy)
    if [[ -f "$_proj_claude_settings" ]]; then
      echo "INFO [claude_turn.sh]: project .claude/settings.json present (cwd=${_cwd}); permission allow/deny applied." >&2
    else
      echo "WARN [claude_turn.sh]: no .claude/settings.json at cwd=${_cwd}; executor under dontAsk will deny most Bash. Run roundtable-setup or copy templates/.claude/settings.json." >&2
    fi
    ;;
  *)
    if [[ -f "$_proj_claude_settings" ]]; then
      echo "INFO [claude_turn.sh]: project .claude/settings.json present (cwd=${_cwd}); permission deny rules applied." >&2
    else
      echo "WARN [claude_turn.sh]: no .claude/settings.json at cwd=${_cwd}; destructive git/secret-read deny rules NOT in effect. Run roundtable-setup." >&2
    fi
    ;;
esac

# Reviewer-likes: do NOT pass --json-schema to claude. Vendor StructuredOutput
# tool routes the verdict into the result-blob's `structured_output` field
# while `result` becomes a short post-message — the 5-part prose body never
# reaches last.md via extract_claude_result. The role system prompt instructs
# claude to embed a fenced ```json verdict block inside the Verification
# section; extract_json_verdict (regex-based) reads it back into verdict.json
# post-turn. Schema in roles/reviewer.schema.json remains the documentation
# contract and is validated post-hoc by tooling that wants strict checks.

_start=$(date +%s)
set +e
# stream-json output: each line is an event; final line has {"type":"result"}.
# Stream goes to stream.jsonl (watchable by idle_watchdog); after run we
# extract the final result event into last.json so downstream extraction
# (jq / extract_claude_result.py) keeps working unchanged.
(
  if command -v timeout >/dev/null 2>&1 && [[ "$timeout_s" -gt 0 ]]; then
    cd "$_cwd" && timeout --signal=TERM --kill-after=10 "${timeout_s}" \
      claude "${_args[@]}" "$(cat "$_prompt")" "${_tools[@]}" \
      < /dev/null > "${hist}/stream.jsonl" 2>"${hist}/stderr.log"
  else
    cd "$_cwd" && claude "${_args[@]}" "$(cat "$_prompt")" "${_tools[@]}" \
      < /dev/null > "${hist}/stream.jsonl" 2>"${hist}/stderr.log"
  fi
) &
_proc_pid=$!
idle_watchdog "$_proc_pid" "${hist}/stream.jsonl" "$idle_s" 30 &
_wd_pid=$!
wait "$_proc_pid"
_ec=$?
kill "$_wd_pid" 2>/dev/null || true
wait "$_wd_pid" 2>/dev/null || true
set -e
_dur=$(( $(date +%s) - _start ))
if [[ "$_ec" -eq 124 ]]; then
  echo "WARN [claude_turn.sh]: claude killed (exit 124) — wall-clock ${timeout_s}s or idle ${idle_s}s exceeded." >&2
fi

# stream-json post-process: pull the final {"type":"result"} event into last.json.
if [[ -s "${hist}/stream.jsonl" ]]; then
  python3 -c '
import json, sys
result = None
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if obj.get("type") == "result":
        result = obj
if result is not None:
    json.dump(result, open(sys.argv[2], "w"))
' "${hist}/stream.jsonl" "${hist}/last.json" 2>/dev/null || true
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
