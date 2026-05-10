#!/usr/bin/env bash
# Initialise a new roundtable thread.
# Requires bash >= 4.0, git.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/_common.sh"

# ── Help ──────────────────────────────────────────────────────────────────────
_usage() {
  cat <<'EOF'
Usage: new_thread.sh <slug> "<one-line goal>"

Initialise a new roundtable thread directory with starter files.

Required:
  <slug>                Thread slug (lowercase, hyphenated), e.g. "my-feature-review".
  "<one-line goal>"     One-sentence description of the thread's goal.

Options:
  -h, --help            Print this help and exit.

Environment:
  ROUNDTABLE_PROJECT_ROOT  Project root (default: auto-detected via git).
                           ROUNDTABLE_REPO_ROOT is a deprecated alias.
  ROUNDTABLE_ROOT          Artifacts root (default:
                           \$ROUNDTABLE_PROJECT_ROOT/.roundtable).

Examples:
  new_thread.sh serve-review-audit "Audit concurrency bugs in the serve module."
  new_thread.sh feature-x-plan "Plan implementation of Feature X from spec."
EOF
}

for _arg in "$@"; do
  if [[ "$_arg" == "-h" || "$_arg" == "--help" ]]; then
    _usage; exit 0
  fi
done

slug="${1:?usage: new_thread.sh <slug> \"<one-line goal>\"}"
goal="${2:?usage: new_thread.sh <slug> \"<one-line goal>\"}"

if [[ ! "$slug" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]]; then
  echo "ERROR: slug must be 1-64 chars of [a-z0-9._-], starting with [a-z0-9]" >&2
  exit 1
fi

dir="${THREADS_ROOT}/${slug}"
if [[ -d "$dir" ]]; then
  echo "ERROR: thread '$slug' already exists at $dir" >&2
  exit 1
fi

# Ensure the artifacts root exists and has a .gitignore on first use.
ensure_artifacts_root

mkdir -p "${dir}"/{artifacts,history,worktrees}
ts="$(iso_now)"

# Render templates with simple substitution.
render() {
  local tmpl="$1" out="$2"
  local safe_goal="${goal//\\/\\\\}"
  safe_goal="${safe_goal//&/\\&}"
  sed -e "s|{{SLUG}}|${slug}|g" \
      -e "s|{{ISO8601}}|${ts}|g" \
      -e "s|{{GOAL_ONE_LINE}}|${safe_goal}|g" \
      "$tmpl" > "$out"
}

render "${SKILL_DIR}/templates/THREAD.md.tmpl"          "${dir}/THREAD.md"
render "${SKILL_DIR}/templates/GOAL.md.tmpl"            "${dir}/GOAL.md"
render "${SKILL_DIR}/templates/OPEN_QUESTIONS.md.tmpl"  "${dir}/OPEN_QUESTIONS.md"

# Refresh `latest` symlink for convenience.
ln -sfn "${dir}" "${THREADS_ROOT}/latest"

echo "thread_dir=${dir}"
echo "Edit GOAL.md (scope / DoD / Plan source). Import a Cursor plan: bash scripts/import_plan.sh ${slug} /path/to/plan.md"
echo "Dispatch only after GOAL.md is ready."
