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
  <slug>                Thread slug (must already exist).
  --role ROLE           planner | executor | reviewer | reviewer-aggregator | devils-advocate | discussant

Options:
  --model MODEL         sonnet | opus | haiku | <full-name> (default from models.json).
  --effort LEVEL        low | medium | high | xhigh | max (default: high).
  --permission-mode M   plan | acceptEdits | auto | dontAsk | bypassPermissions
                        (default: plan for reviewer; acceptEdits otherwise).
  --bare                Pass --bare to claude (skips CLAUDE.md and project customizations).
  --blind               Suppress injection of the latest reviewer verdict block into the
                        prompt. Prevents modal adoption sycophancy (85.5% rate observed
                        when agents see prior verdicts, per arXiv 2605.00914). Use for
                        all parallel reviewers in a multi-reviewer round; the aggregator
                        turn must NOT use --blind (it needs to see all verdicts).
                        Records blind=true in meta.json.
  --worktree NAME       Use/create a git worktree for this turn.
  --allowed-tools LIST  Space-separated tool allowlist (overrides role defaults).
  --addendum TEXT       Extra instructions appended to the prompt.
  --addendum-file FILE  File whose contents are appended to the prompt.
  --timeout-s SECONDS   Hard wallclock cap for claude; on timeout the run is
                        killed and the turn is marked exit=124 (default: 1500).
                        DeepSeek-compat shims have wide tail latency — observed
                        successful reviewer turns up to 1017s. Bump higher if
                        you hit exit=124 with empty last.json.
  -h, --help            Print this help and exit.

Environment:
  ROUNDTABLE_PROJECT_ROOT  Project root (default: auto-detected via git).
  ROUNDTABLE_ROOT          Artifacts root (default: $ROUNDTABLE_PROJECT_ROOT/.roundtable).
  ROUNDTABLE_TAIL_K     Recent turns inlined into prompts (default: 3).
  ROUNDTABLE_TIMEOUT_S  Default for --timeout-s (default: 1500).
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

# ── Argument parsing ─────────────────────────────────────────────────────────
slug="${1:?missing thread slug}"; shift
role=""; model=""; effort="high"; perm=""; bare=0; blind=0
worktree=""; addendum=""; addendum_file=""; allowed_tools_override=""
timeout_s="${ROUNDTABLE_TIMEOUT_S:-1500}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) role="$2"; shift 2;;
    --model) model="$2"; shift 2;;
    --effort) effort="$2"; shift 2;;
    --permission-mode) perm="$2"; shift 2;;
    --bare) bare=1; shift;;
    --blind) blind=1; shift;;
    --worktree) worktree="$2"; shift 2;;
    --allowed-tools) allowed_tools_override="$2"; shift 2;;
    --addendum) addendum="$2"; shift 2;;
    --addendum-file) addendum_file="$2"; shift 2;;
    --timeout-s) timeout_s="$2"; shift 2;;
    *) echo "unknown flag: $1" >&2; exit 2;;
  esac
done
[[ -z "$role" ]] && { echo "ERROR: --role required" >&2; exit 2; }

# Pre-flight: addendum-file must be readable BEFORE we touch anything else.
# Without this, `cat` failure under `set -e` silently aborts the turn
# (observed when Cursor's sandboxed `nohup &` subshell sees an isolated /tmp).
if [[ -n "$addendum_file" && ! -r "$addendum_file" ]]; then
  echo "ERROR [claude_turn.sh]: --addendum-file '$addendum_file' is missing or unreadable." >&2
  echo "  If running inside Cursor's sandboxed Shell tool, write the addendum to a" >&2
  echo "  workspace-visible path (e.g. <thread-dir>/.tmp_addendum.md) instead of /tmp/*" >&2
  echo "  — Cursor's nohup subshell has an isolated /tmp namespace." >&2
  exit 2
fi

if [[ -z "$model" ]]; then
  eval "$( resolve_model claude "$role" "" "$effort" )"
fi

# Default permission-mode: reviewer stays read-only (plan); all other roles
# get acceptEdits so they can write artifacts under the thread dir.
if [[ -z "$perm" ]]; then
  case "$role" in
    reviewer|reviewer-aggregator|devils-advocate) perm="plan";;
    *) perm="acceptEdits";;
  esac
fi

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
if [[ -n "$worktree" ]]; then
  _cwd="$(ensure_worktree "$thread_dir" "$worktree")"
fi

# Compose addendum.
_add="${hist}/addendum.md"
: > "$_add"
[[ -n "$addendum_file" ]] && cat "$addendum_file" >> "$_add"
[[ -n "$addendum" ]] && printf '\n%s\n' "$addendum" >> "$_add"
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
# Note: dynamic system prompt sections (CLAUDE.md, project structure hints,
# recent files) stay enabled by default — they help the agent explore. Use
# --bare for strict isolation.
[[ -n "$model" ]] && _args+=( --model "$model" )
[[ -f "$role_sys" ]] && _args+=( --append-system-prompt "$(cat "$role_sys")" )
[[ "$bare" -eq 1 ]] && _args+=( --bare )

# Per-role tool surface — minimal disablement principle.
# Reviewer roles: write-protection comes from --permission-mode plan (set above);
#   all other tools (WebSearch, WebFetch, Bash, Read, …) stay enabled so the
#   agent has full diagnostic capability.
# Executor / planner / discussant: only destructive git operations are blocked.
# When user provides --allowed-tools override, they take full responsibility.
_tools=()
if [[ -n "${allowed_tools_override:-}" ]]; then
  _tools+=( --allowedTools "$allowed_tools_override" )
else
  case "$role" in
    reviewer|reviewer-aggregator|devils-advocate)
      : ;;  # plan mode + role prompt enforce read-only intent; no allowlist needed.
    *)
      # Truly destructive ops only — fetch/remote/config/checkout origin/* are
      # legitimate exploration tools and stay enabled.
      _tools+=( --disallowedTools "Bash(git push:*) Bash(git push) Bash(git push --force:*) Bash(git rebase:*) Bash(git rebase) Bash(git reset --hard:*) Bash(git reset --hard) Bash(git filter-branch:*) Bash(git update-ref:*)" );;
  esac
fi

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

echo "history=${hist}"
echo "exit_code=${_ec}"
echo "duration_s=${_dur}"
emit_done "$thread_dir" "$hist" "claude" "$role" "$_ec" "$_turn_n" "$_dur"
exit $_ec
}
