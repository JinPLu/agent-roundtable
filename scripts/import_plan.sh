#!/usr/bin/env bash
# import_plan.sh — copy an external plan (e.g. Cursor .plan.md) into
# <thread>/artifacts/PLAN.md and refresh GOAL.md ## Plan source.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${HERE}/lib/import_plan.py" "$@"
