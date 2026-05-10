#!/usr/bin/env bash
# route.sh — signal-based role routing filtered by available actors.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "${HERE}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: route.sh [options]

Wrapper around scripts/lib/route.py. Run with --help to see all options:
  python3 scripts/lib/route.py --help

Common usage:
  bash route.sh --role executor --task-size small
  bash route.sh --role reviewer --diversity --blind
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
