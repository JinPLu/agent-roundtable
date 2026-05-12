#!/usr/bin/env bash
# _resume.sh — Role-aware session-resume policy for codex_turn.sh / claude_turn.sh.
#
# Source this file from a turn script. It exposes three helpers:
#
#   _should_resume <role> <marker_path> <blind_flag> <model_cli_arg>
#       Exit 0 ⇒ resume YES, exit non-zero ⇒ fresh run.
#       Policy (HARD NO if any matches): blind=1, role ∈ {reviewer, reviewer-aggregator,
#       devils-advocate}, env ROUNDTABLE_NO_RESUME=1.
#       Conditional NO: planner role unless ROUNDTABLE_PLANNER_MODE=refine.
#       Marker invalidation: file missing, stored model ≠ current model, ts > 24h old
#       (bypassed when ROUNDTABLE_AUTOPILOT_CONTINUE=1), or git_sha changed
#       (still enforced unless ROUNDTABLE_FORCE_RESUME=1).
#       Override: ROUNDTABLE_FORCE_RESUME=1 skips TTL/git_sha gates but still requires
#       marker present + session_id + matching model.
#
#   _write_session_marker <marker_path> <session_id> <model>
#       Writes {session_id, ts, model, git_sha} JSON, mkdir -p parent.
#
#   _extract_codex_session_id <trace_jsonl_path>
#       Prints the first `thread.started`-class event's session_id, or empty.
#
# All functions are stdlib-only and safe under `set -euo pipefail` (they return
# non-zero on failure rather than abort).
#
#   _marker_persist_eligible <role> <blind_flag>
#       Exit 0 ⇒ caller may persist a new session marker after a successful fresh turn.

_marker_persist_eligible() {
  local role="$1" blind="${2:-0}"
  [[ "$blind" == "1" ]] && return 1
  case "$role" in
    reviewer|reviewer-aggregator|devils-advocate) return 1 ;;
  esac
  return 0
}

_should_resume() {
  local role="$1" marker="$2" blind="${3:-0}" model="${4:-}"

  # HARD NO: --blind suppresses resume regardless of role.
  [[ "$blind" == "1" ]] && return 1

  # HARD NO: roles that must always be fresh for blind / diversity reasons.
  case "$role" in
    reviewer|reviewer-aggregator|devils-advocate) return 1 ;;
  esac

  # HARD NO: explicit user override via flag/env.
  [[ "${ROUNDTABLE_NO_RESUME:-0}" == "1" ]] && return 1

  # Planner: default OFF; only resume when explicitly --mode refine.
  if [[ "$role" == "planner" && "${ROUNDTABLE_PLANNER_MODE:-fresh}" != "refine" ]]; then
    return 1
  fi

  # Marker must exist.
  [[ -f "$marker" ]] || return 1

  # FORCE: skip TTL/git_sha gates — still require session id + model match.
  if [[ "${ROUNDTABLE_FORCE_RESUME:-0}" == "1" ]]; then
    python3 - "$marker" "${model:-}" <<'PY' || return 1
import json, pathlib, sys

m, model = pathlib.Path(sys.argv[1]), sys.argv[2]
try:
    d = json.loads(m.read_text())
except Exception:
    sys.exit(1)
if not d.get("session_id"):
    sys.exit(1)
if str(d.get("model", "")) != str(model):
    sys.exit(1)
sys.exit(0)
PY
    return 0
  fi

  # Validate via Python: TTL + git_sha + model + structural sanity.
  python3 - "$marker" "${ROUNDTABLE_AUTOPILOT_CONTINUE:-0}" "${ROUNDTABLE_PROJECT_ROOT:-}" "${model:-}" <<'PY'
import json, sys, time, subprocess, pathlib

marker_path, autopilot, project_root, model_arg = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    d = json.loads(pathlib.Path(marker_path).read_text())
except Exception:
    sys.exit(1)

if str(d.get("model", "")) != str(model_arg):
    sys.exit(1)

stored_sha = d.get("git_sha") or ""
if stored_sha and project_root:
    try:
        cur_sha = subprocess.check_output(
            ["git", "-C", project_root, "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        cur_sha = ""
    if cur_sha and cur_sha != stored_sha:
        sys.exit(1)

if autopilot != "1":
    try:
        ts = int(d.get("ts", 0))
    except Exception:
        ts = 0
    if not ts or (time.time() - ts) > 86400:
        sys.exit(1)

if not d.get("session_id"):
    sys.exit(1)

sys.exit(0)
PY
  return $?
}

_write_session_marker() {
  local marker="$1" sid="$2" model="$3"
  [[ -z "$sid" || "$sid" == "null" ]] && return 1
  local git_sha=""
  if [[ -n "${ROUNDTABLE_PROJECT_ROOT:-}" ]]; then
    git_sha=$(git -C "$ROUNDTABLE_PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo "")
  fi
  python3 - "$marker" "$sid" "$model" "$git_sha" <<'PY'
import json, sys, time, pathlib
marker, sid, model, sha = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(marker)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
    "session_id": sid,
    "ts": int(time.time()),
    "model": model,
    "git_sha": sha,
}, indent=2))
PY
}

_extract_codex_session_id() {
  local trace="$1"
  [[ -s "$trace" ]] || { echo ""; return 1; }
  python3 - "$trace" <<'PY'
import json, sys
trace = sys.argv[1]
sid = ""
try:
    with open(trace, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line[0] != "{":
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            # Several Codex CLI shapes: top-level type or nested under msg.
            candidates = [evt]
            for k in ("msg", "payload", "data"):
                v = evt.get(k)
                if isinstance(v, dict):
                    candidates.append(v)
            for c in candidates:
                t = c.get("type") or ""
                if t in ("thread.started", "session.started", "session_configured"):
                    cand = c.get("session_id") or c.get("thread_id") or c.get("id")
                    if cand:
                        sid = cand
                        break
                # Some versions emit a top-level "session_id" on first event.
                if not sid and isinstance(c.get("session_id"), str):
                    sid = c["session_id"]
            if sid:
                break
except OSError:
    pass
print(sid)
PY
}
