#!/usr/bin/env bash
# codex_turn.sh — Run one Codex turn against an existing roundtable thread.
# Requires bash >= 4.0, git, codex, python3.
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
Usage: codex_turn.sh <slug> --role ROLE [options]

Required:
  <slug>                Thread slug (must already exist).
  --role ROLE           planner | executor | reviewer | reviewer-aggregator | devils-advocate | discussant

Options:
  -m, --model MODEL     Model name passed to codex (default: from models.json).
  --effort LEVEL        low | medium | high (default: medium).
  -s, --sandbox MODE    read-only | workspace-write | danger-full-access
                        (default: workspace-write for all roles).
  --addendum TEXT       Extra instructions appended to the prompt.
  --addendum-file FILE  File whose contents are appended to the prompt.
  --blind               Suppress injection of the latest reviewer verdict block into the
                        prompt. Prevents modal adoption sycophancy (85.5% rate observed
                        when agents see prior verdicts, per arXiv 2605.00914). Use for
                        all parallel reviewers in a multi-reviewer round; the aggregator
                        turn must NOT use --blind (it needs to see all verdicts).
                        Records blind=true in meta.json.
  --worktree NAME       Use/create a git worktree for this turn.
  --timeout-s SECONDS   Hard wallclock cap for codex; on timeout we still salvage
                        trace.jsonl and emit a turn marked exit=124. Pass 0 to
                        disable timeout entirely (default: 1800).
  -h, --help            Print this help and exit.

Environment:
  ROUNDTABLE_REPO_ROOT  Repo root (default: auto-detected via git).
  ROUNDTABLE_ROOT       Artifacts root (default: $ROUNDTABLE_REPO_ROOT/.roundtable).
  ROUNDTABLE_TAIL_K     Recent turns inlined into prompts (default: 3).
  ROUNDTABLE_TIMEOUT_S  Default for --timeout-s, 0 disables (default: 1800).
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

# ── Argument parsing ─────────────────────────────────────────────────────────
slug="${1:?missing thread slug}"; shift
role=""; model=""; effort="medium"; blind=0
sandbox=""; addendum=""; addendum_file=""; worktree=""
timeout_s="${ROUNDTABLE_TIMEOUT_S:-1800}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) role="$2"; shift 2;;
    -m|--model) model="$2"; shift 2;;
    --effort) effort="$2"; shift 2;;
    --sandbox|-s) sandbox="$2"; shift 2;;
    --blind) blind=1; shift;;
    --addendum) addendum="$2"; shift 2;;
    --addendum-file) addendum_file="$2"; shift 2;;
    --worktree) worktree="$2"; shift 2;;
    --timeout-s) timeout_s="$2"; shift 2;;
    *) echo "unknown flag: $1" >&2; exit 2;;
  esac
done
[[ -z "$role" ]] && { echo "ERROR: --role required" >&2; exit 2; }

# Pre-flight: addendum-file must be readable BEFORE we touch anything else.
# Without this, `cat` failure under `set -e` silently aborts the turn
# (observed when Cursor's sandboxed `nohup &` subshell sees an isolated /tmp).
if [[ -n "$addendum_file" && ! -r "$addendum_file" ]]; then
  echo "ERROR [codex_turn.sh]: --addendum-file '$addendum_file' is missing or unreadable." >&2
  echo "  If running inside Cursor's sandboxed Shell tool, write the addendum to a" >&2
  echo "  workspace-visible path (e.g. <thread-dir>/.tmp_addendum.md) instead of /tmp/*" >&2
  echo "  — Cursor's nohup subshell has an isolated /tmp namespace." >&2
  exit 2
fi

if [[ -z "$model" ]]; then
  eval "$( resolve_model codex "$role" "" "$effort" )"
fi

# All roles default to workspace-write; CWD determines the write boundary.
[[ -z "$sandbox" ]] && sandbox="workspace-write"

thread_dir="$(require_thread "$slug")"
ts_c="$(ts_compact_unique)"
repo_root="$ROUNDTABLE_REPO_ROOT"

# Optional per-actor backend env override. No-op if `.codex_env.local` absent
# (in which case codex uses ~/.codex/{settings,auth}.json as normal).
if load_actor_env codex; then
  echo "INFO [codex_turn.sh]: loaded backend env override from ${SKILL_DIR}/.codex_env.local" >&2
fi

if [[ "$role" == "executor" && -z "${GIT_AUTHOR_EMAIL:-}" && -z "${GIT_COMMITTER_EMAIL:-}" ]]; then
  if ! ( cd "$repo_root" && git config user.email >/dev/null 2>&1 ); then
    echo "WARN [codex_turn.sh]: no GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL exported and no repo user.email; commits by this turn will fail." >&2
  fi
fi

# ── Run one codex turn ───────────────────────────────────────────────────────
hist="${thread_dir}/history/codex/${ts_c}"
mkdir -p "$hist"

# CWD + add-dir: non-executor roles run from thread_dir (workspace-write grants
# artifact writes via -C); --add-dir repo_root grants read access to source.
# Executor runs from repo_root (source writes); --add-dir thread_dir for reading.
# When ROUNDTABLE_PROJECT_ROOT is set and differs from repo_root, mount it too —
# otherwise agents see project file paths in the prompt but can't open them.
_cwd="$repo_root"
_extra_dirs=( "$thread_dir" )
if [[ -n "$worktree" ]]; then
  _cwd="$(ensure_worktree "$thread_dir" "$worktree")"
elif [[ "$role" != "executor" ]]; then
  _cwd="$thread_dir"
  _extra_dirs=( "$repo_root" )
fi
if [[ -n "${ROUNDTABLE_PROJECT_ROOT:-}" && "$ROUNDTABLE_PROJECT_ROOT" != "$repo_root" && "$ROUNDTABLE_PROJECT_ROOT" != "$_cwd" ]]; then
  _extra_dirs+=( "$ROUNDTABLE_PROJECT_ROOT" )
fi

# Compose addendum.
_add="${hist}/addendum.md"
: > "$_add"
[[ -n "$addendum_file" ]] && cat "$addendum_file" >> "$_add"
[[ -n "$addendum" ]] && printf '\n%s\n' "$addendum" >> "$_add"
if [[ "$role" == "executor" ]]; then
  cat >> "$_add" <<'GEOF'

## Codex /goal bridge

This thread has a durable objective in `GOAL.md`. Codex has the goal model tools enabled.

1. At the START of your turn, call `get_goal` to inspect any existing goal state.
2. If `get_goal` returns no goal (or an outdated objective), call `create_goal` with the contents of `GOAL.md` (the "Goal" / "Definition of Done" sections) so the runtime can track DoD progress, accounting, and budget across continuation turns.
3. If you complete a DoD item during this turn, call `update_goal` to record the progress.
4. Do NOT call `pause_goal` / `resume_goal` / `clear_goal` — those are user-controlled.
5. The goal state is persisted across runs; subsequent turns of this thread will see what you set.

The 5-part output discipline still applies: the goal bridge is observability, not a substitute for the turn body.
GEOF
fi

mapfile -t _warnings < <(warn_addendum_sanity "$_add" "codex_turn.sh")
# Blind mode: suppress the prior verdict block to prevent modal adoption sycophancy
# (85.5% adoption rate when agents see prior verdicts, per arXiv 2605.00914).
_prompt="$(ROUNDTABLE_SKIP_LATEST_VERDICT="${blind}" build_prompt "$thread_dir" "$role" "$_add" "${hist}/prompt.md")"

_args=(
  --skip-git-repo-check
  -C "$_cwd"
  -s "$sandbox"
  -c approval_policy="never"
  --enable goals
  -c model_reasoning_effort="${effort}"
  -o "${hist}/last.md"
  --json
)
for _d in "${_extra_dirs[@]}"; do
  _args+=( --add-dir "$_d" )
done
[[ -n "$model" ]] && _args+=( -m "$model" )

_start=$(date +%s)
set +e
if command -v timeout >/dev/null 2>&1 && [[ "$timeout_s" -gt 0 ]]; then
  timeout --signal=TERM --kill-after=10 "${timeout_s}" \
    codex exec "${_args[@]}" "$(cat "$_prompt")" \
    < /dev/null > "${hist}/trace.jsonl" 2>&1
else
  codex exec "${_args[@]}" "$(cat "$_prompt")" \
    < /dev/null > "${hist}/trace.jsonl" 2>&1
fi
_ec=$?
set -e
_dur=$(( $(date +%s) - _start ))
if [[ "$_ec" -eq 124 ]]; then
  echo "WARN [codex_turn.sh]: codex exec exceeded ${timeout_s}s; killed by timeout (exit 124)." >&2
fi

# Salvage last.md from trace.jsonl if -o failed to flush.
if [[ ! -s "${hist}/last.md" && -s "${hist}/trace.jsonl" ]]; then
  python3 "${SKILL_DIR}/scripts/lib/salvage_codex_trace.py" \
    "${hist}/trace.jsonl" "${hist}/last.md" 2>/dev/null || true
  if [[ -s "${hist}/last.md" ]]; then
    echo "NOTE: last.md was missing (codex did not flush -o); salvaged from trace.jsonl" >&2
  fi
fi

_ts=$(iso_now)
_turn_n=""
if [[ -s "${hist}/last.md" ]]; then
  _turn_n="$(append_turn_md "${thread_dir}/THREAD.md" "codex" "$role" "$_ts" "${hist}/last.md")"
  echo "appended_turn=${_turn_n}"
else
  echo "WARNING: last.md is empty AND no agent_message found in trace; check ${hist}/trace.jsonl" >&2
fi

if [[ ( "$role" == "reviewer" || "$role" == "reviewer-aggregator" || "$role" == "devils-advocate" ) && -s "${hist}/last.md" ]]; then
  extract_json_verdict "${hist}/last.md" "${hist}/verdict.json" "codex/${ts_c}"
fi

write_meta "${hist}/meta.json" "codex" "${model:-default}" "$effort" "$role" "$sandbox" "$_ec" "$_dur" "$hist" "${OPENAI_BASE_URL:-unset}" "${_warnings[@]}"

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
emit_done "$thread_dir" "$hist" "codex" "$role" "$_ec" "$_turn_n" "$_dur"
exit $_ec
}
