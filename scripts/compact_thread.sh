#!/usr/bin/env bash
# compact_thread.sh — Summarise old turns into THREAD_SUMMARY.md.
#
# Keeps the most-recent K turns verbatim in THREAD.md; older turns are
# compacted (Read fields stripped, Verification truncated) and appended/
# prepended to THREAD_SUMMARY.md.
#
# Usage:
#   compact_thread.sh <slug> [--keep K] [--dry-run]
#
# Options:
#   --keep K     Number of recent turns to keep verbatim (default: 6).
#   --dry-run    Print what would happen; don't write any files.
#
# After compaction THREAD_SUMMARY.md can be fed back to build_prompt (section 5)
# so agents see the summary of old turns without the full text.
{
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/_common.sh"

_usage() {
  cat <<'EOF'
Usage: compact_thread.sh <slug> [--keep K] [--dry-run]

Summarise old turns into THREAD_SUMMARY.md; keep the last K turns in THREAD.md.

Options:
  --keep K     Turns to keep verbatim (default: 6).
  --dry-run    Print plan without writing files.
  -h, --help   Print this help and exit.
EOF
}

for _arg in "$@"; do
  case "$_arg" in -h|--help) _usage; exit 0;; esac
done

slug="${1:?missing thread slug}"; shift
keep_k=6
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) keep_k="$2"; shift 2;;
    --dry-run) dry_run=1; shift;;
    *) echo "unknown flag: $1" >&2; exit 2;;
  esac
done

thread_dir="$(require_thread "$slug")"
thread_md="${thread_dir}/THREAD.md"
summary_md="${thread_dir}/THREAD_SUMMARY.md"

if [[ ! -f "$thread_md" ]]; then
  echo "ERROR: THREAD.md not found at $thread_md" >&2
  exit 1
fi

total_turns=$(grep -cE '^## Turn [0-9]' "$thread_md" 2>/dev/null) || total_turns=0
echo "Thread: $slug | total turns: $total_turns | keeping last: $keep_k"

if (( total_turns <= keep_k )); then
  echo "Nothing to compact (${total_turns} turns ≤ keep_k=${keep_k})."
  exit 0
fi

to_compact=$(( total_turns - keep_k ))
echo "Compacting turns 1–${to_compact} into THREAD_SUMMARY.md, keeping turns $((to_compact+1))–${total_turns} in THREAD.md."

if [[ "$dry_run" -eq 1 ]]; then
  echo "[dry-run] No files written."
  exit 0
fi

# Run Python helper: tail goes to stdout (→ new THREAD.md), summary lines go to
# stderr prefixed with "SUMMARY:" (→ THREAD_SUMMARY.md).
_tail_tmp=$(mktemp "${thread_dir}/.compact_tail_XXXXXXXX.md")
_summary_tmp=$(mktemp "${thread_dir}/.compact_summary_XXXXXXXX.md")
trap 'rm -f "$_tail_tmp" "$_summary_tmp" 2>/dev/null' EXIT

python3 "${SKILL_DIR}/scripts/lib/compact_thread.py" \
  "$thread_md" "$keep_k" \
  > "$_tail_tmp" \
  2> >(grep '^SUMMARY:' | sed 's/^SUMMARY://' > "$_summary_tmp" || true)

# Sanity check: tail must not be empty.
if [[ ! -s "$_tail_tmp" ]]; then
  echo "ERROR: compaction produced empty tail; aborting, THREAD.md unchanged." >&2
  rm -f "$_tail_tmp" "$_summary_tmp"
  exit 1
fi

# Build new THREAD_SUMMARY.md: existing summary (if any) + new compacted block.
if [[ -f "$summary_md" && -s "$summary_md" ]]; then
  {
    cat "$summary_md"
    printf '\n\n---\n\n'
    cat "$_summary_tmp"
  } > "${summary_md}.new"
  mv -f "${summary_md}.new" "$summary_md"
else
  mv -f "$_summary_tmp" "$summary_md"
fi

# Replace THREAD.md with the kept tail.
mv -f "$_tail_tmp" "$thread_md"

echo "Done. THREAD.md now has ${keep_k} turns. THREAD_SUMMARY.md updated."
echo "  THREAD.md:         $thread_md"
echo "  THREAD_SUMMARY.md: $summary_md"
}
