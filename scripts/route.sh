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
                [--diversity]
                [--blind]
                [--companion auto|MODEL]
                [-m|--model ALIAS]
                [--estimate [--effort low|medium|high|xhigh] [--turns N]]

Recommend model aliases from models.json:role_defaults after filtering by
available actors and applying optional task signals.

Signals (all optional, backward-compatible):
  --budget cheap       Sort by input cost ascending.
  --budget premium     Sort by best benchmark score descending.
  --latency fast       Exclude cursor-subagent (unbounded queue latency).
  --output-heavy       Exclude models with max_output_k < 128K tokens.
  --diversity          Return at most one candidate per distinct actor family,
                       enforcing cross-vendor diversity (Hard Rule #7).
  --blind              Tag the routing output with blind=true; signals to the
                       caller that every dispatched reviewer turn must include
                       --blind to prevent modal adoption sycophancy (85.5%
                       rate without this guard, per arXiv 2605.00914).
  --companion auto     After ranking the primary candidate, also suggest the
  --companion MODEL    cheapest available model from a *different* actor as a
                       companion dispatch (Principle A: cheap cross-vendor
                       companion alongside any expensive dispatch). The
                       companion must always be dispatched with --blind.
  -m, --model ALIAS    Filter candidates to a single alias (typically paired
                       with --estimate to price the model the user picked).
                       Accepts any alias present in the registry, even if not
                       in role_defaults.
  --estimate           Append a USD cost band per candidate (and companion)
                       via scripts/lib/estimate_cost.py. Default-off: without
                       this flag, route.sh output is byte-identical to the
                       pre-estimator behaviour. The Dispatch Confirmation
                       block in SKILL.md REQUIRES this flag.
  --effort LEVEL       Estimator effort tier (low|medium|high|xhigh,
                       default medium). Only meaningful with --estimate.
  --turns N            Pre-multiply the estimate by N turns (default 1).
                       Only meaningful with --estimate.

Cheap companion convention (Principle A):
  Every expensive dispatch (cursor-claude-4.7-opus / cursor-claude-4.6-sonnet /
  cursor-gemini-3.1-pro) MUST have a cheap cross-vendor companion running in
  parallel. See SKILL.md §Multi-agent quality mode for the pairing table.
  companion dispatch = same slug, same role, --blind, cheapest other-actor model.

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
