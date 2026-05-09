#!/usr/bin/env bash
# Shared helpers for agent-roundtable turn scripts. Source this; do not exec.
# Requires bash >= 4.0.

set -euo pipefail

# ── Project-root resolution ──────────────────────────────────────────────────
# Single source of truth: ROUNDTABLE_PROJECT_ROOT is the user's project.
#   - threads live at $PROJECT_ROOT/.roundtable/threads/<slug>/
#   - agents are mounted onto $PROJECT_ROOT for source reads/writes
#   - if `.planning/` exists under it, key files are listed in every prompt
# Resolution priority:
#   1. Explicit env var ROUNDTABLE_PROJECT_ROOT.
#   2. ROUNDTABLE_REPO_ROOT (deprecated alias, still accepted).
#   3. git rev-parse --show-toplevel from caller's cwd.
#   4. Hard error.
# Warn if the resolved root accidentally is the skill's own dir.
if [[ -z "${ROUNDTABLE_PROJECT_ROOT:-}" ]]; then
  if [[ -n "${ROUNDTABLE_REPO_ROOT:-}" ]]; then
    ROUNDTABLE_PROJECT_ROOT="$ROUNDTABLE_REPO_ROOT"
  else
    _rt_git_cwd=$(git rev-parse --show-toplevel 2>/dev/null || true)
    if [[ -n "$_rt_git_cwd" ]]; then
      ROUNDTABLE_PROJECT_ROOT="$_rt_git_cwd"
    else
      echo "ERROR: Cannot determine project root; set ROUNDTABLE_PROJECT_ROOT=/path/to/your/project or run from inside a git repo." >&2
      exit 1
    fi
    unset _rt_git_cwd
  fi
fi
_rt_skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$ROUNDTABLE_PROJECT_ROOT" == "$_rt_skill_dir" ]]; then
  echo "WARN [_common.sh]: ROUNDTABLE_PROJECT_ROOT=${ROUNDTABLE_PROJECT_ROOT} is the skill's own directory." >&2
  echo "                  Agents would explore the skill, not your project. Set" >&2
  echo "                  ROUNDTABLE_PROJECT_ROOT=/path/to/your/project to fix this." >&2
fi
unset _rt_skill_dir
export ROUNDTABLE_PROJECT_ROOT

# Legacy alias — keep ROUNDTABLE_REPO_ROOT pointing at the same dir for any
# downstream code that still reads it.
export ROUNDTABLE_REPO_ROOT="${ROUNDTABLE_REPO_ROOT:-$ROUNDTABLE_PROJECT_ROOT}"

ROUNDTABLE_ROOT="${ROUNDTABLE_ROOT:-${ROUNDTABLE_PROJECT_ROOT}/.roundtable}"
export ROUNDTABLE_ROOT

THREADS_ROOT="${ROUNDTABLE_ROOT}/threads"

# SKILL_DIR: resolved from _common.sh's own location — never hard-coded.
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── load_actor_env ───────────────────────────────────────────────────────────
# Source per-actor env override file `<SKILL_DIR>/.<actor>_env.local` if it
# exists. Used to point a single actor's CLI at a different backend (e.g.
# claude → DeepSeek-via-Anthropic-compat endpoint) without polluting the
# parent shell's env or interfering with the user's interactive CLI runs.
#
# The file is a plain POSIX shell snippet of `export FOO=bar` lines. Template
# lives at `<SKILL_DIR>/.<actor>_env.example`. The `.local` variant is
# gitignored because it contains credentials.
#
# Args: actor (claude | codex | …)
load_actor_env() {
  local actor="$1"
  local f="${SKILL_DIR}/.${actor}_env.local"
  if [[ -r "$f" ]]; then
    # shellcheck disable=SC1090
    set -a
    source "$f"
    set +a
    return 0
  fi
  return 1
}

# ── Utility helpers ──────────────────────────────────────────────────────────

ensure_artifacts_root() {
  mkdir -p "${ROUNDTABLE_ROOT}"
  local gi="${ROUNDTABLE_ROOT}/.gitignore"
  if [[ ! -f "$gi" ]]; then
    printf '*\n!.gitignore\n' > "$gi"
  fi
}

iso_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
ts_compact() { date -u +"%Y%m%dT%H%M%SZ"; }

warn_addendum_sanity() {
  local addendum_file="$1" source_label="${2:-roundtable}"
  [[ -s "$addendum_file" ]] || return 0

  local bytes msg
  bytes=$(wc -c < "$addendum_file" | tr -d ' ')

  if [[ "$bytes" =~ ^[0-9]+$ && "$bytes" -gt "${ROUNDTABLE_ADDENDUM_WARN_BYTES:-8192}" ]]; then
    msg="WARN [${source_label}]: addendum is ${bytes} bytes; consider splitting the turn or moving background to GOAL.md/artifacts."
    printf '%s\n' "$msg" >&2
    printf '%s\n' "$msg"
  fi
}

safe_repo_git() {
  if ! command -v timeout >/dev/null 2>&1; then
    return 0
  fi
  timeout 3 git -C "$ROUNDTABLE_REPO_ROOT" --no-optional-locks "$@" 2>/dev/null || true
}

emit_repo_context() {
  local proj="$ROUNDTABLE_PROJECT_ROOT"
  local branch head
  branch="$(safe_repo_git rev-parse --abbrev-ref HEAD | head -n 1)"
  branch="${branch:-unknown}"
  head="$(safe_repo_git log -1 --format=%h | head -n 1)"
  head="${head:-unknown}"

  printf '## Project context\n'
  printf -- '- project root: `%s`  branch: `%s`  HEAD: `%s`\n' "$proj" "$branch" "$head"
  [[ -f "${proj}/AGENTS.md" ]] && printf -- '- AGENTS.md: `%s/AGENTS.md`\n' "$proj"
  [[ -d "${proj}/.cursor/rules" ]] && printf -- '- rules: `%s/.cursor/rules/`\n' "$proj"
  if [[ -d "${proj}/.planning" ]]; then
    printf -- '- planning dir: `%s/.planning/` — read the index files below before relying on summaries:\n' "$proj"
    local pf
    for pf in STATE.json DASHBOARD.md NARRATIVE.md paper/NARRATIVE.md \
               paper/STATUS_REPORT_*.md runbooks/WORK_ORDERS.md \
               runbooks/DPO_EXECUTION_PLAN_*.md; do
      local full="${proj}/.planning/${pf}"
      for match in ${full}; do
        [[ -f "$match" ]] && printf -- '  - `%s`\n' "$match"
      done
    done
  fi
  printf '\n'
}

# Per-turn unique history dir suffix; combines second-precision UTC ts with
# bash $$ + 4-byte random hex so concurrent dispatches in the same second do
# not collide on `history/<actor>/<ts>/` (was a pre-2026-05-08 race bug).
ts_compact_unique() {
  local ts rand
  ts=$(date -u +"%Y%m%dT%H%M%SZ")
  rand=$(od -An -N2 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' || printf '%04x' $$)
  printf '%s_%d_%s' "$ts" "$$" "$rand"
}

require_thread() {
  local slug="$1"
  local dir="${THREADS_ROOT}/${slug}"
  if [[ ! -d "$dir" ]]; then
    echo "ERROR: thread '$slug' not found under ${THREADS_ROOT}" >&2
    echo "Hint: run scripts/new_thread.sh <slug> '<one-line goal>' first." >&2
    exit 2
  fi
  echo "$dir"
}

next_turn_n() {
  local thread_md="$1"
  local n
  n=$(grep -E '^## Turn [0-9]+' "$thread_md" 2>/dev/null \
        | sed -E 's/^## Turn ([0-9]+).*/\1/' \
        | sort -n | tail -1 || true)
  echo $(( ${n:-0} + 1 ))
}

# Append a turn block to THREAD.md.
# Args: thread_md actor role iso8601 body_file
append_turn_md() {
  local thread_md="$1" actor="$2" role="$3" ts="$4" body_file="$5"
  local n; n=$(next_turn_n "$thread_md")
  {
    printf '\n## Turn %s — %s / %s — %s\n\n' "$n" "$actor" "$role" "$ts"
    cat "$body_file"
    printf '\n---\n'
  } >> "$thread_md"
  echo "$n"
}

# ── build_prompt ─────────────────────────────────────────────────────────────
# Assemble the standard prompt: stable prefix + thread context + role + addendum.
# Args: thread_dir role addendum_file out_path
#
# Prompt ordering (for provider cache efficiency):
#   1. STABLE PREFIX — conventions, output discipline, artifact rules
#   2. THREAD METADATA — absolute paths, stable per thread
#   3. GOAL.md inlined — stable per thread
#   4. REPO CONTEXT — compact git/rules pointers, failures degrade
#   5. EARLIER HISTORY — THREAD_SUMMARY.md if present
#   6. RECENT TURNS — last K turns from THREAD.md
#   7. LATEST REVIEWER VERDICT — pruned verdict.json if present
#   8. OPEN QUESTIONS — only if non-trivial
#   9. YOUR ROLE THIS TURN
#  10. SPECIFIC ASK — addendum
#
# Env vars:
#   ROUNDTABLE_TAIL_K              — recent turns inlined (default 3)
#   ROUNDTABLE_COMPACT_READ        — strip Read fields in recent turns (default 1)
#   ROUNDTABLE_SKIP_DISCIPLINE     — omit output-discipline reminder (default 0; set 1 when
#                                    role sys prompt covers it to save ~300 chars per prompt)
#   ROUNDTABLE_SKIP_REPO_CONTEXT   — omit repo context block (default 0)
#   ROUNDTABLE_SKIP_ROLE_SYS       — omit role guidelines injection (default 0; set 1 for
#                                    claude_turn.sh which delivers via --append-system-prompt)
#   ROUNDTABLE_SKIP_LATEST_VERDICT — omit the latest reviewer verdict block (default 0; set 1
#                                    for blind reviewer turns to prevent modal adoption
#                                    sycophancy — 85.5% adoption rate observed when agents see
#                                    prior verdicts, per arXiv 2605.00914)
build_prompt() {
  local thread_dir="$1" role="$2" addendum_file="$3" out_path="${4:-}"
  local out
  if [[ -n "$out_path" ]]; then
    mkdir -p "$(dirname "$out_path")"
    out=$(mktemp "${out_path}.XXXXXXXX.tmp")
  else
    mkdir -p "${thread_dir}/.cache"
    out=$(mktemp "${thread_dir}/.cache/_prompt_$(ts_compact)_XXXXXXXX.md")
  fi

  local tail_k="${ROUNDTABLE_TAIL_K:-3}"
  local current_history_dir=""
  if [[ -n "$out_path" ]]; then
    current_history_dir="$(dirname "$out_path")"
  fi

  {
    # ── 1. STABLE PREFIX ────────────────────────────────────────────────────
    # The independence rule lives in roles/_independence_rule.md and is included
    # by every role system prompt (single source of truth — do NOT re-embed it
    # here, or it ships into every Claude turn twice via --append-system-prompt).
    printf '# Roundtable conventions\n\n'

    # Auto-skip when role system prompt exists (it already includes the format spec).
    local _skip_disc="${ROUNDTABLE_SKIP_DISCIPLINE:-0}"
    if [[ "$_skip_disc" != "1" ]]; then
      local _rdsk="$role"; [[ "$_rdsk" == "reviewer-aggregator" ]] && _rdsk="reviewer"
      [[ -f "${SKILL_DIR}/roles/${_rdsk}.system.md" ]] && _skip_disc=1
    fi
    if [[ "$_skip_disc" != "1" ]]; then
      printf '**Output discipline**: your **final message** MUST be ONLY the five-part turn body '
      printf '(no preamble, no closing remarks — the chat parent appends it verbatim to THREAD.md):\n'
      printf '`**Read** / **Did** / **Verification** / **Open questions** / **Hand-off**`\n'
      printf 'Artifacts → `%s/artifacts/`. All on-disk text → **English**.\n\n' "$thread_dir"
    fi

    # ── 2. THREAD METADATA ──────────────────────────────────────────────────
    printf '## Thread: `%s`\n' "$thread_dir"
    printf 'Key files: `GOAL.md` `THREAD.md` `OPEN_QUESTIONS.md` `artifacts/`'
    if [[ -f "${thread_dir}/THREAD_SUMMARY.md" ]]; then
      printf ' `THREAD_SUMMARY.md`'
    fi
    printf '\nOnly the last %s turns are inlined below; read `THREAD.md` for full history.\n\n' "${ROUNDTABLE_TAIL_K:-3}"

    # ── 3. GOAL.md INLINED ──────────────────────────────────────────────────
    printf '## Goal\n```\n'
    cat "${thread_dir}/GOAL.md"
    printf '\n```\n\n'

    # ── 4. REPO CONTEXT ──────────────────────────────────────────────────────
    if [[ "${ROUNDTABLE_SKIP_REPO_CONTEXT:-0}" != "1" ]]; then
      emit_repo_context
    fi

    # ── 5. EARLIER HISTORY (rolling summary, only if file exists) ───────────
    if [[ -f "${thread_dir}/THREAD_SUMMARY.md" ]]; then
      printf '## Earlier history (mechanically compacted — Read fields stripped, Verification truncated)\n'
      printf 'If you need exact details from old turns, read `%s/THREAD.md` directly.\n\n' "$thread_dir"
      cat "${thread_dir}/THREAD_SUMMARY.md"
      printf '\n\n'
    fi

    # ── 6. RECENT TURNS (last K full blocks) ────────────────────────────────
    local total_turns
    total_turns=$(grep -cE '^## Turn [0-9]' "${thread_dir}/THREAD.md" 2>/dev/null) || total_turns=0
    printf '## Recent turns (last K=%s of total %s)\n' "$tail_k" "$total_turns"
    printf '```\n'
    if [[ "${ROUNDTABLE_COMPACT_READ:-1}" == "0" ]]; then
      python3 - "${thread_dir}/THREAD.md" "$tail_k" <<'PY' || true
import sys, re, pathlib

thread_md = pathlib.Path(sys.argv[1]).read_text()
k = int(sys.argv[2])

blocks = re.split(r'(?=^## Turn \d+)', thread_md, flags=re.MULTILINE)
turn_blocks = [b for b in blocks if re.match(r'^## Turn \d+', b.strip())]

tail = turn_blocks[-k:] if k < len(turn_blocks) else turn_blocks
print("".join(tail), end="")
PY
    else
      python3 "${SKILL_DIR}/scripts/lib/compact_recent_turns.py" "${thread_dir}/THREAD.md" "$tail_k" || true
    fi
    printf '\n```\n\n'

    # Blind mode: suppress the prior verdict block to prevent modal adoption sycophancy.
    # Activated by ROUNDTABLE_SKIP_LATEST_VERDICT=1 (set by --blind in turn scripts).
    if [[ "${ROUNDTABLE_SKIP_LATEST_VERDICT:-0}" != "1" ]]; then
      python3 "${SKILL_DIR}/scripts/lib/latest_verdict_block.py" "$thread_dir" "$current_history_dir" 2>/dev/null || true
    fi

    # ── 7. OPEN QUESTIONS (only if file has substantive content) ──────────────
    local oq_file="${thread_dir}/OPEN_QUESTIONS.md"
    if [[ -f "$oq_file" ]] && grep -qE '^[^#[:space:]]|^- \[' "$oq_file" 2>/dev/null; then
      printf '## Open questions\n```\n'
      cat "$oq_file"
      printf '\n```\n\n'
    fi

    # ── 8. YOUR ROLE THIS TURN ───────────────────────────────────────────────
    printf '## Your role this turn\n`%s`\n\n' "$role"

    # ── 8b. ROLE GUIDELINES (injected when role system prompt file exists) ───
    # For claude_turn.sh this is redundant (system prompt sent via --append-system-prompt);
    # for codex_turn.sh and cursor subagents this is the only delivery path.
    local _role_sys_key_bp="$role"
    [[ "$role" == "reviewer-aggregator" ]] && _role_sys_key_bp="reviewer"
    local _role_sys_bp="${SKILL_DIR}/roles/${_role_sys_key_bp}.system.md"
    if [[ -f "$_role_sys_bp" ]] && [[ "${ROUNDTABLE_SKIP_ROLE_SYS:-0}" != "1" ]]; then
      printf '## Role guidelines\n'
      cat "$_role_sys_bp"
      printf '\n\n'
    fi

    # ── 9. SPECIFIC ASK ──────────────────────────────────────────────────────
    if [[ -s "$addendum_file" ]]; then
      printf '## Specific ask for THIS turn\n'
      cat "$addendum_file"
      printf '\n'
    fi
  } > "$out"

  if [[ -n "$out_path" ]]; then
    mv -f "$out" "$out_path"
    echo "$out_path"
  else
    echo "$out"
  fi
}

# ── resolve_model ────────────────────────────────────────────────────────────
# Resolve a model alias + effort from <SKILL_DIR>/models.json.
# Args: actor role [model_override] [effort_override]
# Output (eval-friendly): model=<cli_arg> effort=<level>
resolve_model() {
  local actor="$1" role="$2" model_override="${3:-}" effort_override="${4:-}"
  local registry="${SKILL_DIR}/models.json"
  # Fall back to the shipped example catalog if the user hasn't run
  # `backend.sh init` yet — keeps routing-hint defaults working out of the box.
  [[ -f "$registry" ]] || registry="${SKILL_DIR}/models.example.json"
  if [[ ! -f "$registry" ]] || ! command -v python3 >/dev/null 2>&1; then
    printf 'model=%s\neffort=%s\n' "$model_override" "${effort_override:-medium}"
    return
  fi
  python3 - "$registry" "$actor" "$role" "$model_override" "$effort_override" <<'PY'
import json, sys
reg=json.load(open(sys.argv[1]))
actor, role = sys.argv[2], sys.argv[3]
mo, eo = sys.argv[4], sys.argv[5]
# role_defaults[role] is a list of model aliases, not a dict keyed by actor.
aliases = reg.get("role_defaults", {}).get(role, [])
models = reg.get("models", {})
alias = mo or ""
if not alias:
    # Find the first alias whose "actor" field matches the requested actor.
    matched = next((a for a in aliases if models.get(a, {}).get("actor") == actor), None)
    if matched:
        alias = matched
    elif aliases:
        print(f"WARN: no alias for actor '{actor}' in role '{role}'; falling back to first alias '{aliases[0]}'", file=sys.stderr)
        alias = aliases[0]
effort = eo or "medium"
m = models.get(alias, {})
cli_arg = m.get("cli_arg", alias)
print(f"model={cli_arg}")
print(f"effort={effort}")
PY
}

# ── write_meta ───────────────────────────────────────────────────────────────
# Capture a meta.json after a run.
# Args: meta_path actor model effort role sandbox exit_code duration_s history_dir [backend_env] [warnings...]
write_meta() {
  local path="$1" actor="$2" model="$3" effort="$4" role="$5" sandbox="$6" exit_code="$7" dur="$8" hist="$9"
  shift 9
  local backend_env="${1:-unset}"
  if [[ $# -gt 0 ]]; then shift; fi
  local warnings=("$@")
  local diff_stat
  diff_stat=$(cd "$ROUNDTABLE_REPO_ROOT" && git diff --stat 2>/dev/null | tail -1 || echo "")
  python3 - "$path" "$actor" "$model" "$effort" "$role" "$sandbox" "$exit_code" "$dur" "$hist" "$diff_stat" "$(iso_now)" "$backend_env" "${warnings[@]}" <<'PY'
import json
import pathlib
import sys

path, actor, model, effort, role, sandbox, exit_code, dur, hist, diff_stat, ts, backend_env = sys.argv[1:13]
warnings = sys.argv[13:]
meta = {
    "actor": actor,
    "model": model,
    "effort": effort,
    "role": role,
    "sandbox_or_perm": sandbox,
    "exit_code": int(exit_code),
    "duration_s": int(dur),
    "history_dir": hist,
    "git_diff_summary": diff_stat,
    "usage": {},
    "ts": ts,
    "warnings": warnings,
    "backend_env": backend_env or "unset",
}
pathlib.Path(path).write_text(json.dumps(meta, indent=2))
PY
}

# ── emit_done ────────────────────────────────────────────────────────────────
# Fire the standard completion signal at the end of every turn.
# Two-layer signal:
#   1. Sentinel file — `<history_dir>/.done` is written with KV payload.
#   2. STDOUT marker — `ROUNDTABLE_DONE: thread=… actor=… role=…`
#      printed as the LAST stdout line for terminal-tail watchers.
#
# Args: thread_dir history_dir actor role exit_code turn_n duration_s
emit_done() {
  local thread_dir="$1" history_dir="$2" actor="$3" role="$4" \
        exit_code="$5" turn_n="${6:-}" duration_s="${7:-0}"
  local slug
  slug="$(basename "$thread_dir")"
  local payload
  payload=$(printf 'thread=%s actor=%s role=%s exit=%s turn=%s history=%s thread_dir=%s duration_s=%s' \
    "$slug" "$actor" "$role" "$exit_code" "$turn_n" "$history_dir" "$thread_dir" "$duration_s")

  if [[ -d "$history_dir" ]]; then
    printf '%s ts=%s\n' "$payload" "$(iso_now)" > "${history_dir}/.done" 2>/dev/null || true
  fi

  printf 'ROUNDTABLE_DONE: %s\n' "$payload"
}

# ── Worktree helper ──────────────────────────────────────────────────────────
# Args: thread_dir name
ensure_worktree() {
  local thread_dir="$1" name="$2"
  local repo="$ROUNDTABLE_REPO_ROOT"
  local wt="${thread_dir}/worktrees/${name}"
  if [[ -d "$wt" ]]; then echo "$wt"; return; fi
  mkdir -p "${thread_dir}/worktrees"
  ( cd "$repo" && git worktree add -B "roundtable/${name}" "$wt" HEAD ) >&2
  echo "$wt"
}

# ── extract_json_verdict ─────────────────────────────────────────────────────
# Extract first ```json ... ``` block from a file and save to dest.
# Fails softly: logs warning to stderr, writes nothing if block missing/invalid.
# Args: src_file dest_file label
extract_json_verdict() {
  local src="$1" dest="$2" label="${3:-turn}"
  python3 - "$src" "$dest" "$label" <<'PY'
import sys, re, json, pathlib

src, dest, label = sys.argv[1], sys.argv[2], sys.argv[3]
txt = pathlib.Path(src).read_text()

m = re.search(r'```json\n(.*?)\n```', txt, re.DOTALL)
if not m:
    print(f"WARNING [{label}]: no ```json``` block found in {src}; verdict.json not written.", file=sys.stderr)
    sys.exit(0)

raw = m.group(1).strip()
try:
    parsed = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"WARNING [{label}]: JSON parse error in {src}: {e}; verdict.json not written.", file=sys.stderr)
    sys.exit(0)

pathlib.Path(dest).write_text(json.dumps(parsed, indent=2))
print(f"verdict.json written: {dest}", file=sys.stderr)
PY
}
