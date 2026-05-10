#!/usr/bin/env bash
# wait_for_done.sh - poll for one or more turn .done sentinel files.
#
# Why: turn scripts emit `<thread_dir>/history/<actor>/<ts>/.done` and a
# `ROUNDTABLE_DONE: ...` line on stdout when a turn finishes. The chat parent
# previously polled with `nohup ... &; echo $!` + ad-hoc `ps -p` checks,
# which silently lose early failures because the launcher exits in <100ms
# (see audit R2 / docs/advanced.md "Avoid nohup &"). This helper is the
# documented poller — exit 0 only when the expected number of turns finished.
#
# Usage:
#   wait_for_done.sh <thread_dir> <actor> [<expected_count=1>] [<timeout_s=3600>]
#
# Args:
#   thread_dir       Path to .roundtable/threads/<slug>/
#   actor            Sub-dir name under history/ (codex / claude / cursor-subagent)
#   expected_count   Number of distinct .done files required (default 1)
#   timeout_s        Hard wall-clock cap (default 3600 = 60min)
#
# Exit:
#   0   expected_count .done files appeared within timeout_s
#   124 timeout (matches GNU `timeout` convention)
#   2   bad usage (missing args / dir not found)
#
# Streams to stderr:
#   - "[Ns] actor=X done=Y/Z" status every 30s
#   - tail of the latest stream.jsonl / trace.jsonl when present (so the
#     parent can see live progress vs silence)

set -euo pipefail

usage() {
  cat >&2 <<EOF
Usage: $0 <thread_dir> <actor> [<expected_count=1>] [<timeout_s=3600>]

Examples:
  $0 .roundtable/threads/my-slug claude 1 1800
  $0 .roundtable/threads/my-slug codex 3            # wait for 3 codex turns
EOF
}

[[ $# -lt 2 || $# -gt 4 ]] && { usage; exit 2; }

thread_dir="$1"
actor="$2"
expected="${3:-1}"
timeout_s="${4:-3600}"

[[ -d "$thread_dir" ]] || { echo "ERROR: thread_dir not found: $thread_dir" >&2; exit 2; }
case "$actor" in
  codex|claude|cursor-subagent) ;;
  *) echo "ERROR: actor must be codex / claude / cursor-subagent (got $actor)" >&2; exit 2;;
esac

[[ "$expected" =~ ^[0-9]+$ ]] || { echo "ERROR: expected_count must be a non-negative integer" >&2; exit 2; }
[[ "$timeout_s" =~ ^[0-9]+$ ]] || { echo "ERROR: timeout_s must be a non-negative integer" >&2; exit 2; }

actor_dir="$thread_dir/history/$actor"
mkdir -p "$actor_dir"

start=$(date +%s)
last_status=0
while true; do
  now=$(date +%s)
  elapsed=$(( now - start ))
  done_count=$(find "$actor_dir" -mindepth 2 -maxdepth 2 -name .done -type f 2>/dev/null | wc -l)

  if [[ "$done_count" -ge "$expected" ]]; then
    echo "[${elapsed}s] actor=${actor} done=${done_count}/${expected} OK" >&2
    exit 0
  fi

  if (( now - last_status >= 30 )); then
    last_status=$now
    # Find the newest in-progress turn dir (the one without .done)
    latest=$(find "$actor_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
             | sort | tail -1)
    if [[ -n "$latest" ]]; then
      stream=""
      for f in "$latest/stream.jsonl" "$latest/trace.jsonl"; do
        [[ -f "$f" ]] && stream="$f" && break
      done
      if [[ -n "$stream" ]]; then
        sz=$(stat -c %s "$stream" 2>/dev/null || echo 0)
        ev=$(wc -l < "$stream" 2>/dev/null || echo 0)
        echo "[${elapsed}s] actor=${actor} done=${done_count}/${expected} stream=${sz}B events=${ev}" >&2
      else
        echo "[${elapsed}s] actor=${actor} done=${done_count}/${expected} (no stream/trace yet)" >&2
      fi
    else
      echo "[${elapsed}s] actor=${actor} done=${done_count}/${expected} (no turn dir yet)" >&2
    fi
  fi

  if [[ "$elapsed" -ge "$timeout_s" ]]; then
    echo "ERROR [wait_for_done]: timeout ${timeout_s}s reached; got ${done_count}/${expected} .done files" >&2
    exit 124
  fi

  sleep 5
done
