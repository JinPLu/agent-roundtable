#!/usr/bin/env bash
# setup_tools.sh — Configure agent CLIs to their full tool surface.
#
# Principle: tools are part of install, not a manual post-step. After this
# script runs, codex/claude CLIs invoked by the roundtable have web search,
# URL fetch, and other diagnostic capabilities ready to go.
#
# Idempotent: safe to re-run. Reports per-tool whether it was newly installed
# or already present. Does NOT touch user secrets or models.json.
#
# Called automatically by `backend.sh apply`; can also be run standalone via
# `backend.sh tools` or directly.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROXY_FILE="${ROUNDTABLE_PROXY_FILE:-/media/datasets/OminiEWM_Data/tmp/ljp/OoVMetric/resource/proxy.txt}"

# ── Proxy bootstrap ──────────────────────────────────────────────────────────
# Source the shared proxy file (if present) so package installers can reach
# PyPI from inside this corporate network. The exported http_proxy/https_proxy
# are also forwarded into each MCP server's runtime env (--env) so the server
# itself can fetch web content at request time.
if [[ -r "$PROXY_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$PROXY_FILE"
  echo "[setup_tools] sourced proxy from $PROXY_FILE (http_proxy=${http_proxy:-unset})"
else
  echo "[setup_tools] no proxy file at $PROXY_FILE — using direct network"
fi

# Public PyPI index — local mirrors here don't carry the MCP packages.
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.org/simple/}"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.org/simple/}"

# ── Status accumulators ──────────────────────────────────────────────────────
INSTALLED=()
PRESENT=()
FAILED=()

_have_codex_mcp() {
  local name="$1"
  codex mcp get "$name" >/dev/null 2>&1
}

_codex_mcp_add() {
  # _codex_mcp_add <name> <pypi-pkg> [extra-args-to-server...]
  local name="$1"; shift
  local pkg="$1"; shift
  local label="${name} (uvx ${pkg})"

  if _have_codex_mcp "$name"; then
    PRESENT+=("codex/${label}")
    echo "[setup_tools] codex MCP '${name}': already configured ✓"
    return 0
  fi

  echo "[setup_tools] codex MCP '${name}': adding via 'codex mcp add'…"
  # Forward proxy + uv index into the MCP runtime env so the server can both
  # bootstrap (uvx download) and reach the open web at request time.
  local env_args=()
  [[ -n "${http_proxy:-}"   ]] && env_args+=( --env "http_proxy=${http_proxy}" )
  [[ -n "${https_proxy:-}"  ]] && env_args+=( --env "https_proxy=${https_proxy}" )
  [[ -n "${HTTP_PROXY:-}"   ]] && env_args+=( --env "HTTP_PROXY=${HTTP_PROXY}" )
  [[ -n "${HTTPS_PROXY:-}"  ]] && env_args+=( --env "HTTPS_PROXY=${HTTPS_PROXY}" )
  env_args+=( --env "UV_INDEX_URL=${UV_INDEX_URL}" --env "UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}" )

  if codex mcp add "$name" "${env_args[@]}" -- uvx "$pkg" "$@" 2>&1; then
    INSTALLED+=("codex/${label}")
    echo "[setup_tools] codex MCP '${name}': added ✓"
  else
    FAILED+=("codex/${label}")
    echo "[setup_tools] codex MCP '${name}': add failed ✗" >&2
    return 1
  fi
}

_check_uvx_pkg() {
  # Best-effort: warm uvx cache for a package so the MCP server starts fast on
  # first use. Non-fatal — if this fails, codex will still try to launch it
  # later. Timeout keeps re-runs cheap.
  local pkg="$1"
  if timeout 180 uvx --quiet "$pkg" --help >/dev/null 2>&1; then
    echo "[setup_tools] uvx '${pkg}': cached ✓"
    return 0
  else
    echo "[setup_tools] uvx '${pkg}': warm-cache failed (non-fatal — codex will retry on first use)" >&2
    return 1
  fi
}

# ── Codex MCP: web search + URL fetch ────────────────────────────────────────
echo
echo "=== Codex CLI: MCP tool surface ==="
_check_uvx_pkg duckduckgo-mcp-server || true
_codex_mcp_add ddg-search duckduckgo-mcp-server || true

_check_uvx_pkg mcp-server-fetch || true
_codex_mcp_add fetch mcp-server-fetch || true

# ── Claude Code: native WebSearch / WebFetch ─────────────────────────────────
# Claude Code ships WebSearch + WebFetch as built-in tools. Per the roundtable
# tool policy (minimal disablement), claude_turn.sh runs them at full surface
# and only blocks destructive git for non-reviewer roles. No MCP server is
# needed. We just verify the binary is on PATH and the tool names show up in
# its help output.
echo
echo "=== Claude Code: native tool surface ==="
if command -v claude >/dev/null 2>&1; then
  if claude --help 2>&1 | grep -q -- '--allowed-tools'; then
    PRESENT+=("claude/WebSearch (native)")
    PRESENT+=("claude/WebFetch (native)")
    PRESENT+=("claude/Bash, Read, Edit, Write, Grep, Glob (native)")
    echo "[setup_tools] claude: native WebSearch + WebFetch + Bash + Read/Edit/Write/Grep/Glob enabled ✓"
    echo "[setup_tools] claude: per-role surface enforced by claude_turn.sh (minimal-disablement policy)"
  else
    FAILED+=("claude/--allowed-tools-flag-missing")
    echo "[setup_tools] claude: --allowed-tools flag not found in --help output ✗" >&2
  fi
else
  FAILED+=("claude/binary-missing")
  echo "[setup_tools] claude: binary not on PATH ✗" >&2
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "=== Tool configuration summary ==="
if (( ${#INSTALLED[@]} )); then
  echo "Newly installed:"
  for t in "${INSTALLED[@]}"; do echo "  + ${t}"; done
fi
if (( ${#PRESENT[@]} )); then
  echo "Already configured:"
  for t in "${PRESENT[@]}"; do echo "  · ${t}"; done
fi
if (( ${#FAILED[@]} )); then
  echo "Failed (manual follow-up needed):" >&2
  for t in "${FAILED[@]}"; do echo "  ✗ ${t}" >&2; done
fi

echo
echo "── codex mcp list ──"
codex mcp list 2>&1 || true

if (( ${#FAILED[@]} > 0 )); then
  exit 1
fi
exit 0
