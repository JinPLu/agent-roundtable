#!/usr/bin/env bash
# Install or remove agent-roundtable Cursor hooks into ~/.cursor/hooks.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "${1:-}" == "--uninstall" ]]; then
  shift
  exec python3 "$ROOT/scripts/lib/install_hooks.py" --uninstall "$@"
fi
exec python3 "$ROOT/scripts/lib/install_hooks.py" \
  --template "$ROOT/templates/hooks.json.tmpl" \
  --skill-dir "$ROOT" \
  "$@"
