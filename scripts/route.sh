#!/usr/bin/env bash
# route.sh — signal-based role routing filtered by available actors.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "${HERE}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: route.sh --role ROLE [--top N] [--json] [--cursor-subagent]
                [--budget cheap|normal|premium]
                [--latency fast|normal]
                [--output-heavy]

Recommend model aliases from models.json:role_defaults after filtering by
available actors and applying optional task signals.

Signals (all optional, backward-compatible):
  --budget cheap       Sort by input cost ascending.
  --budget premium     Sort by best benchmark score descending.
  --latency fast       Exclude cursor-subagent (unbounded queue latency).
  --output-heavy       Exclude models with max_output < 128K tokens.

Actor detection:
  codex requires `codex login status` or CODEX_AVAILABLE=1.
  claude requires `claude auth status` or CLAUDE_AVAILABLE=1.
  cursor-subagent requires CURSOR_SUBAGENT_AVAILABLE=1 or --cursor-subagent.
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

exec python3 "${SKILL_DIR}/scripts/lib/route.py" "$@"
