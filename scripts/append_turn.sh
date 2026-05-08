#!/usr/bin/env bash
# append_turn.sh — append an externally-produced 5-part turn body to THREAD.md.
#
# Used when the chat parent dispatched a Cursor Task subagent. Provides the
# same THREAD.md append + meta.json + emit_done integration as the CLI wrappers.
# Requires bash >= 4.0, python3.
#
# Body is wrapped in a brace group so bash parses it fully before executing,
# preventing the streaming-parser race when a turn modifies this file in-place.
{
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/_common.sh"

_usage() {
  cat <<'EOF'
Usage: append_turn.sh <slug> --actor ACTOR --role ROLE --body-file FILE [options]

Required:
  <slug>                  Thread slug (must already exist).
  --actor ACTOR           Actor identifier (e.g. cursor-subagent).
  --role ROLE             planner | executor | reviewer | reviewer-aggregator | discussant
  --body-file FILE        5-part turn body to append verbatim.

Options:
  --model NAME            Model alias for meta.json.
  --task-subagent-type T  Subagent type for meta.json audit trail.
  --effort LEVEL          low | medium | high (default: medium).
  --tokens-in N           Input tokens (optional).
  --tokens-out N          Output tokens (optional).
  --prompt-file FILE      Exact prompt sent to the external subagent; copied to history prompt.md.
  --duration-s N          Wall-clock seconds (default: 0).
  -h, --help              Print this help.
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

slug="${1:?missing thread slug}"; shift
actor=""; role=""; model=""; effort="medium"
body_file=""; prompt_file=""; subagent_type=""
tokens_in=""; tokens_out=""; duration_s=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --actor) actor="$2"; shift 2;;
    --role) role="$2"; shift 2;;
    --body-file) body_file="$2"; shift 2;;
    --prompt-file) prompt_file="$2"; shift 2;;
    --model) model="$2"; shift 2;;
    --task-subagent-type) subagent_type="$2"; shift 2;;
    --effort) effort="$2"; shift 2;;
    --tokens-in) tokens_in="$2"; shift 2;;
    --tokens-out) tokens_out="$2"; shift 2;;
    --duration-s) duration_s="$2"; shift 2;;
    *) echo "unknown flag: $1" >&2; exit 2;;
  esac
done
[[ -z "$actor"     ]] && { echo "ERROR: --actor required"     >&2; exit 2; }
[[ -z "$role"      ]] && { echo "ERROR: --role required"      >&2; exit 2; }
[[ -z "$body_file" ]] && { echo "ERROR: --body-file required" >&2; exit 2; }
[[ -s "$body_file" ]] || { echo "ERROR: body-file '$body_file' is empty or missing" >&2; exit 2; }
if [[ -n "$prompt_file" && ! -s "$prompt_file" ]]; then
  echo "ERROR: prompt-file '$prompt_file' is empty or missing" >&2
  exit 2
fi

thread_dir="$(require_thread "$slug")"
ts_c="$(ts_compact_unique)"
hist="${thread_dir}/history/${actor}/${ts_c}"
mkdir -p "$hist"

prompt_bytes=""
if [[ -n "$prompt_file" ]]; then
  cp "$prompt_file" "${hist}/prompt.md"
  prompt_bytes=$(wc -c < "$prompt_file" | tr -d ' ')
else
  echo "WARN [append_turn.sh]: no prompt-file recorded for external actor." >&2
fi
cp "$body_file" "${hist}/last.md"

ts="$(iso_now)"
turn_n="$(append_turn_md "${thread_dir}/THREAD.md" "$actor" "$role" "$ts" "${hist}/last.md")"
echo "appended_turn=${turn_n}"

if [[ "$role" == "reviewer" || "$role" == "reviewer-aggregator" ]]; then
  extract_json_verdict "${hist}/last.md" "${hist}/verdict.json" "${actor}/${ts_c}"
fi

write_meta "${hist}/meta.json" "$actor" "${model:-default}" "$effort" "$role" \
  "task" "0" "$duration_s" "$hist" "${ANTHROPIC_BASE_URL:-unset}"

# Patch tokens / subagent_type into meta.json if provided.
if [[ -n "$tokens_in" || -n "$tokens_out" || -n "$subagent_type" || -n "$prompt_bytes" ]]; then
  python3 - "${hist}/meta.json" "$tokens_in" "$tokens_out" "$subagent_type" "$prompt_bytes" <<'PY'
import json, pathlib, sys
mp = pathlib.Path(sys.argv[1])
ti, to, sa, prompt_bytes = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
m = json.loads(mp.read_text())
if sa: m["task_subagent_type"] = sa
if prompt_bytes: m["prompt_bytes"] = int(prompt_bytes)
u = m.get("usage") or {}
if ti: u["tokens_in"] = int(ti)
if to: u["tokens_out"] = int(to)
m["usage"] = u
mp.write_text(json.dumps(m, indent=2))
PY
fi

echo "history=${hist}"
echo "exit_code=0"
echo "duration_s=${duration_s}"
emit_done "$thread_dir" "$hist" "$actor" "$role" "0" "$turn_n" "$duration_s"
}
