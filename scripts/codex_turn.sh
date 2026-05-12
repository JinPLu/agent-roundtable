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
# CX1: role-aware session-resume helpers.
source "${HERE}/lib/_resume.sh"

_usage() {
  cat <<'EOF'
Usage: codex_turn.sh <slug> --role ROLE [options]

Required:
  <slug>            Thread slug (must already exist).
  --role ROLE       planner | executor | reviewer | reviewer-aggregator | devils-advocate | discussant

Options:
  -m, --model M     Model passed to codex (default: from models.json).
  --effort LEVEL    low | medium | high (default: medium).
  --task TEXT       Per-turn instruction appended to the prompt.
  --task-file FILE  Per-turn instruction read from file (use for long inputs).
  --blind           Suppress prior reviewer verdict — required for parallel reviewers.
                    Also forces fresh (resume HARD NO).
  --no-resume       Force fresh run even if a valid session marker exists.
  --force-resume    Resume even when TTL / git_sha checks would normally fail (debug).
  --mode MODE       planner only: fresh (default) or refine (enables resume).
  --force           Bypass dispatch confirmation gate (CI/scripted use only).
  -h, --help        Print this help.

Environment:
  ROUNDTABLE_PROJECT_ROOT       Project root (default: caller's git toplevel).
  ROUNDTABLE_TIMEOUT_S          Wallclock cap in seconds, 0 disables (default: 1800).
  ROUNDTABLE_AUTOPILOT_CONTINUE Set =1 by /roundtable-goal autopilot to bypass
                                resume TTL gate (git_sha still enforced).
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

# ── Argument parsing ─────────────────────────────────────────────────────────
slug="${1:?missing thread slug}"; shift
role=""; model=""; effort="medium"; blind=0
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
    --no-resume) export ROUNDTABLE_NO_RESUME=1; shift;;
    --force-resume) export ROUNDTABLE_FORCE_RESUME=1; shift;;
    --mode) export ROUNDTABLE_PLANNER_MODE="$2"; shift 2;;
    --force) export ROUNDTABLE_FORCE=1; shift;;
    *) echo "unknown flag: $1 (try -h)" >&2; exit 2;;
  esac
done
[[ -z "$role" ]] && { echo "ERROR: --role required" >&2; exit 2; }

# Gate 3.2: require dispatch confirmation unless --force or ROUNDTABLE_DISPATCH_CONFIRMED=1
check_dispatch_confirmed

# Pre-flight: task-file must be readable BEFORE we touch anything else.
# Without this, `cat` failure under `set -e` silently aborts the turn.
if [[ -n "$task_file" && ! -r "$task_file" ]]; then
  echo "ERROR [codex_turn.sh]: --task-file '$task_file' missing or unreadable." >&2
  echo "  If running inside Cursor's sandboxed Shell tool, write the file to a" >&2
  echo "  workspace-visible path (Cursor's nohup subshell has an isolated /tmp)." >&2
  exit 2
fi

# Always resolve via models.json so an alias passed as --model (e.g.
# `codex-cli-gpt-5.5`) is translated to its cli_arg (e.g. `gpt-5.5`).
# Without this, an orchestrator-supplied alias goes verbatim to the
# CLI / proxy. cialloapi.cn rejects bare aliases like `gpt-5` per
# https://doc.claude-api.org/faq.
eval "$( resolve_model codex "$role" "$model" "$effort" )"

# Sandbox per role: read roles get vendor-enforced read-only (parity with
# Claude's --permission-mode plan); only executor needs workspace-write.
# Planner / reviewer artifact text comes back via -o / trace.jsonl and the
# parent script (or P2.1 capture) writes it under artifacts/ — the model
# itself does not need write access to do its job.
case "$role" in
  reviewer|reviewer-aggregator|devils-advocate|planner|discussant|researcher|researcher-deep) sandbox="read-only" ;;
  *) sandbox="workspace-write" ;;
esac

thread_dir="$(require_thread "$slug")"
ts_c="$(ts_compact_unique)"
repo_root="$ROUNDTABLE_PROJECT_ROOT"

# Gate 3.3: same-vendor reviewer diversity check (warning only)
if [[ "$role" == "reviewer-aggregator" ]]; then
  python3 "$SKILL_DIR/scripts/lib/check_review_diversity.py" "$thread_dir" || true
  # exit 2 = warning only; don't block aggregation
fi

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

# CWD + add-dir: executor runs from project root (so source writes are inside
# the workspace-write sandbox); non-executor roles run from thread_dir to
# scope writes to artifacts/, with project root added as read-only via --add-dir.
if [[ "$role" == "executor" ]]; then
  _cwd="$ROUNDTABLE_PROJECT_ROOT"
  _add_dir="$thread_dir"
else
  _cwd="$thread_dir"
  _add_dir="$ROUNDTABLE_PROJECT_ROOT"
fi

# Compose addendum from task / task-file.
_add="${hist}/addendum.md"
: > "$_add"
[[ -n "$task_file" ]] && cat "$task_file" >> "$_add"
[[ -n "$task" ]] && printf '\n%s\n' "$task" >> "$_add"
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

_codex_profile=""
if [[ -f "${HOME}/.codex/config.toml" ]] && grep -q 'roundtable-managed begin' "${HOME}/.codex/config.toml" 2>/dev/null; then
  _cp_prof="roundtable-${role}"
  if grep -qF "[profiles.${_cp_prof}]" "${HOME}/.codex/config.toml" 2>/dev/null; then
    _codex_profile="$_cp_prof"
  fi
fi

_args=(
  --skip-git-repo-check
  -C "$_cwd"
  --add-dir "$_add_dir"
)
[[ -n "$_codex_profile" ]] && _args+=( --profile "$_codex_profile" )
_args+=( -s "$sandbox" )
[[ -z "$_codex_profile" ]] && _args+=( -c approval_policy="never" )
_args+=(
  --enable goals
  -c model_reasoning_effort="${effort}"
  -o "${hist}/last.md"
  --json
)
[[ -n "$model" ]] && _args+=( -m "$model" )

# ── CX1: role-aware session resume ───────────────────────────────────────────
# Marker path keys on role + model so different models cannot accidentally
# share a session. _should_resume enforces the role/blind policy table and
# TTL/git_sha invalidation; see scripts/lib/_resume.sh for the contract.
_session_marker_model="$(printf '%s' "${model:-default}" | tr '/:' '__')"
_session_marker="${thread_dir}/.codex_session.${role}.${_session_marker_model}.json"
_resume_sid=""
if _should_resume "$role" "$_session_marker" "$blind" "${model:-}"; then
  _resume_sid="$(jq -r '.session_id // empty' "$_session_marker" 2>/dev/null || \
                  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('session_id',''))" \
                    "$_session_marker" 2>/dev/null || echo "")"
fi
if [[ -n "$_resume_sid" ]]; then
  echo "INFO [codex_turn.sh]: resuming codex session ${_resume_sid:0:8}… (role=${role}, model=${_session_marker_model})" >&2
fi

# Reviewer-likes: do NOT pass --output-schema to codex. Vendor strict-mode
# rewrites the agent_message into pure JSON and drops the 5-part body. The
# role system prompt instructs codex to embed a fenced ```json verdict block
# inside the Verification section; extract_json_verdict (regex-based) reads
# it back into verdict.json post-turn. Schema in roles/reviewer.schema.json
# remains the documentation contract and is validated post-hoc by tooling
# that wants strict checks.

_start=$(date +%s)
# When resuming, pass the addendum-only "delta task" so we don't re-spend
# input tokens on the full prompt that the session has already seen. The
# fresh path keeps using the full assembled prompt for safety.
if [[ -n "$_resume_sid" ]]; then
  _prompt_text="$(cat "$_add")"
  [[ -z "$_prompt_text" ]] && _prompt_text="Continue per the durable goal — produce the next 5-part turn body."
else
  _prompt_text="$(cat "$_prompt")"
fi

set +e
# Run codex in a backgrounded subshell so an idle_watchdog can monitor
# trace.jsonl (which codex --json streams continuously) and SIGTERM the
# process if no event arrives for ${idle_s}s. Wall-clock timeout is the
# fail-safe; idle_watchdog is the primary stuck-detector.
(
  if [[ -n "$_resume_sid" ]]; then
    if command -v timeout >/dev/null 2>&1 && [[ "$timeout_s" -gt 0 ]]; then
      timeout --signal=TERM --kill-after=10 "${timeout_s}" \
        codex exec resume "$_resume_sid" "${_args[@]}" "$_prompt_text" \
        < /dev/null > "${hist}/trace.jsonl" 2> >(tee "${hist}/cli_stderr.log" >> "${hist}/trace.jsonl")
    else
      codex exec resume "$_resume_sid" "${_args[@]}" "$_prompt_text" \
        < /dev/null > "${hist}/trace.jsonl" 2> >(tee "${hist}/cli_stderr.log" >> "${hist}/trace.jsonl")
    fi
  else
    if command -v timeout >/dev/null 2>&1 && [[ "$timeout_s" -gt 0 ]]; then
      timeout --signal=TERM --kill-after=10 "${timeout_s}" \
        codex exec "${_args[@]}" "$_prompt_text" \
        < /dev/null > "${hist}/trace.jsonl" 2> >(tee "${hist}/cli_stderr.log" >> "${hist}/trace.jsonl")
    else
      codex exec "${_args[@]}" "$_prompt_text" \
        < /dev/null > "${hist}/trace.jsonl" 2> >(tee "${hist}/cli_stderr.log" >> "${hist}/trace.jsonl")
    fi
  fi
) &
_proc_pid=$!
idle_watchdog "$_proc_pid" "${hist}/trace.jsonl" "$idle_s" 30 &
_wd_pid=$!
_scope_pid=""
if [[ "$role" == "executor" ]]; then
  python3 "${SKILL_DIR}/scripts/lib/scope_watcher.py" "$_proc_pid" "${hist}/trace.jsonl" "$thread_dir" &
  _scope_pid=$!
fi
wait "$_proc_pid"
_ec=$?
kill "$_wd_pid" 2>/dev/null || true
wait "$_wd_pid" 2>/dev/null || true
[[ -n "$_scope_pid" ]] && kill "$_scope_pid" 2>/dev/null || true
wait "$_scope_pid" 2>/dev/null || true
set -e
_dur=$(( $(date +%s) - _start ))

# CX1: capture session_id from a successful (or even partially-successful)
# run, but only when fresh — resumed runs reuse the same id we just used.
# Marker write is best-effort: never alter exit status.
if [[ -z "$_resume_sid" && "$_ec" -eq 0 ]] && _marker_persist_eligible "$role" "$blind"; then
  _new_sid="$(_extract_codex_session_id "${hist}/trace.jsonl" || true)"
  if [[ -n "$_new_sid" ]]; then
    _write_session_marker "$_session_marker" "$_new_sid" "${model:-}" || \
      echo "WARN [codex_turn.sh]: failed to write session marker ${_session_marker}" >&2
  fi
fi
if [[ "$_ec" -eq 124 ]]; then
  echo "WARN [codex_turn.sh]: codex exec killed (exit 124) — wall-clock ${timeout_s}s or idle ${idle_s}s exceeded." >&2
fi

# Salvage last.md from trace.jsonl if -o failed to flush.
if [[ ! -s "${hist}/last.md" && -s "${hist}/trace.jsonl" ]]; then
  python3 "${SKILL_DIR}/scripts/lib/salvage_codex_trace.py" \
    "${hist}/trace.jsonl" "${hist}/last.md" 2>/dev/null || true
  if [[ -s "${hist}/last.md" ]]; then
    echo "NOTE: last.md was missing (codex did not flush -o); salvaged from trace.jsonl" >&2
  fi
fi

# Planner under read-only sandbox cannot itself write artifacts/plan-*.md;
# capture the extracted output into the thread artifacts dir for operators
# (mirrors claude_turn.sh's plan-claude-<ts>.md path so Phase A can glob
# `artifacts/plan-*-<ts>.md` across vendors).
_plan_art=""
if [[ "$role" == "planner" && "$sandbox" == "read-only" && -s "${hist}/last.md" ]]; then
  mkdir -p "${thread_dir}/artifacts"
  _plan_art="${thread_dir}/artifacts/plan-codex-${ts_c}.md"
  cp "${hist}/last.md" "${_plan_art}"
  echo "plan_artifact=${_plan_art}" >&2
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

patch_blind_meta "${hist}/meta.json" "$blind"

_real_usd="null"
python3 "${SKILL_DIR}/scripts/lib/extract_codex_usage.py" "${hist}/trace.jsonl" --write "${hist}/usage.json" >/dev/null 2>&1 || true
if [[ -f "${hist}/usage.json" ]]; then
  _real_usd="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['real_usd'] if d.get('usage_found') else 'null')" "${hist}/usage.json" 2>/dev/null || echo null)"
fi

# Append project-wide usage record (best-effort; never alter exit status).
# See scripts/lib/log_turn_usage.py and docs/research/COST_ESTIMATION-2026-05-10.md §6.4.
finalize_turn "$thread_dir" "$hist" "codex" "$role" "$_ec" "$_turn_n" "$_dur" \
  "$slug" "${model:-default}" "$effort" "${hist}/trace.jsonl" "null" "$_real_usd"
exit $_ec
}
