#!/usr/bin/env bash
# backend.sh — Point the codex or claude actor at any OpenAI/Anthropic-compatible
# endpoint. Reads <SKILL_DIR>/models.json (user-editable, gitignored) and writes
# <SKILL_DIR>/.<actor>_env.local (chmod 600, gitignored), which {codex,claude}_turn.sh
# source before invoking the CLI.
#
# Usage:
#   backend.sh init                            # seed models.json from models.example.json (no-op if it already exists)
#   backend.sh apply [codex|claude]            # read models.json, write .<actor>_env.local for each `active` actor
#   backend.sh show  [codex|claude]            # inspect current state (api_key redacted)
#   backend.sh clear <codex|claude>            # remove .<actor>_env.local
#   backend.sh codex  <base-url> <api-key> [default-model]                     # one-shot direct write (bypasses models.json)
#   backend.sh claude <base-url> <api-key> [opus-model] [sonnet-model] [haiku-model]
#
# Default flow (file-based, secret never enters chat or agent context):
#   1. backend.sh init            # creates <SKILL_DIR>/models.json from the example catalog
#   2. user opens <SKILL_DIR>/models.json in their editor:
#        - finds (or adds) a model entry under `models.<id>`
#        - adds `"endpoint": {"base_url": "...", "api_key": "..."}` to that entry
#        - sets `active.codex` and/or `active.claude` to the model id
#        - saves
#   3. backend.sh apply           # writes the .<actor>_env.local files

set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

_usage() { sed -n '/^# backend\.sh/,/^[^#]/{ /^[^#]/d; s/^# \{0,1\}//; p; }' "$0"; }

case "${1:-}" in
  -h|--help|"") _usage; exit 0;;
esac

cmd="$1"; shift

# ── helpers ──────────────────────────────────────────────────────────────────

_models_file() {
  local f="${SKILL_DIR}/models.json"
  if [[ -r "$f" ]]; then echo "$f"; return; fi
  echo "${SKILL_DIR}/models.example.json"
}

_show_local() {
  local actor="${1:-}"
  local f="${SKILL_DIR}/.${actor}_env.local"
  if [[ -r "$f" ]]; then
    printf '── .%s_env.local (%s) ──\n' "$actor" "$f"
    grep -E '^export [A-Z_]+=' "$f" | sed -E 's/(TOKEN|API_KEY)=.*/\1=***redacted***/'
  else
    printf '── .%s_env.local: not configured ──\n' "$actor"
  fi
}

_show_models_summary() {
  local mf
  mf="$(_models_file)"
  printf '── models.json (%s) ──\n' "$mf"
  python3 - "$mf" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
active = data.get("active") or {}
models = data.get("models") or {}
for actor in ("codex", "claude"):
    mid = active.get(actor)
    if not mid:
        print(f"  active.{actor}: <not set>")
        continue
    m = models.get(mid)
    if not m:
        print(f"  active.{actor}: {mid!r} -> ERROR: no such model in `models` block")
        continue
    ep = m.get("endpoint") or {}
    has_base = bool(ep.get("base_url"))
    has_key = bool(ep.get("api_key"))
    cli = m.get("cli_arg", mid)
    status = (
        "ready" if (has_base and has_key) else
        ("base_url only — api_key blank" if has_base else
         ("api_key only — base_url blank" if has_key else "no endpoint block"))
    )
    print(f"  active.{actor}: {mid!r}  cli_arg={cli!r}  status={status}")
ep_count = sum(1 for m in models.values() if isinstance(m, dict) and (m.get("endpoint") or {}).get("api_key"))
print(f"  catalog: {len(models)} model entries; {ep_count} with credentialed endpoints")
PY
}

# ── commands ─────────────────────────────────────────────────────────────────

case "$cmd" in
  init)
    src="${SKILL_DIR}/models.example.json"
    dst="${SKILL_DIR}/models.json"
    [[ -r "$src" ]] || { echo "ERROR: $src not found." >&2; exit 2; }
    if [[ -e "$dst" ]]; then
      echo "$dst already exists; not overwriting. Edit it directly, or delete it first to reseed."
      exit 0
    fi
    cp "$src" "$dst"
    chmod 600 "$dst"
    echo "wrote $dst (chmod 600 — keeps api_keys readable only by you)"
    echo
    echo "Next steps:"
    echo "  1. Open $dst in your editor"
    echo "  2. Find or add the model entry you'll use, add an \`endpoint\` block:"
    echo '       "endpoint": { "base_url": "https://...", "api_key": "sk-..." }'
    echo "  3. Set \`active.codex\` / \`active.claude\` to the model id"
    echo "  4. Save, then run: $0 apply"
    ;;

  show)
    if [[ "${1:-}" == "codex" || "${1:-}" == "claude" ]]; then
      _show_local "$1"
    else
      _show_models_summary
      echo
      _show_local codex
      echo
      _show_local claude
    fi
    ;;

  clear)
    actor="${1:?which actor: codex|claude}"
    rm -f "${SKILL_DIR}/.${actor}_env.local"
    echo "cleared ${SKILL_DIR}/.${actor}_env.local"
    ;;

  apply)
    only="${1:-}"
    mf="${SKILL_DIR}/models.json"
    [[ -r "$mf" ]] || { echo "ERROR: $mf not found. Run: $0 init" >&2; exit 2; }
    python3 - "$mf" "$0" "$only" <<'PY'
import json, sys, subprocess, pathlib
mf, script, only = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.loads(pathlib.Path(mf).read_text())
active = data.get("active") or {}
models = data.get("models") or {}
targets = [only] if only else ["codex", "claude"]
applied = 0
for actor in targets:
    if actor not in ("codex", "claude"):
        print(f"ERROR: unknown actor {actor!r}", file=sys.stderr); sys.exit(2)
    mid = active.get(actor)
    if not mid:
        print(f"SKIP {actor}: active.{actor} is null in models.json", file=sys.stderr); continue
    m = models.get(mid)
    if not m:
        print(f"ERROR {actor}: active.{actor} = {mid!r} but no such entry in models block", file=sys.stderr); sys.exit(2)
    declared_actor = m.get("actor")
    if declared_actor and declared_actor != actor:
        print(f"WARN  {actor}: model {mid!r} is registered as actor={declared_actor!r}", file=sys.stderr)
    ep = m.get("endpoint") or {}
    base, key = ep.get("base_url"), ep.get("api_key")
    if not base or not key:
        print(f"SKIP {actor}: model {mid!r} has no endpoint.base_url or api_key set", file=sys.stderr); continue
    cli_arg = m.get("cli_arg", mid)
    cmd = [script, actor, base, key, cli_arg]
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        sys.exit(r.returncode)
    applied += 1
    print(f"APPLIED actor={actor} model={mid} cli_arg={cli_arg} base_url={base}")
if applied == 0:
    print("Nothing applied. Edit models.json: set `active.{codex,claude}` to a model id whose entry has an `endpoint` block with both base_url and api_key.", file=sys.stderr)
    sys.exit(2)
PY
    ;;

  codex)
    base_url="${1:?missing base-url}"; api_key="${2:?missing api-key}"
    default_model="${3:-}"
    out="${SKILL_DIR}/.codex_env.local"
    {
      printf '# Auto-generated by scripts/backend.sh on %s.\n' "$(date -u +%FT%TZ)"
      printf 'export OPENAI_BASE_URL=%q\n' "$base_url"
      printf 'export OPENAI_API_KEY=%q\n'  "$api_key"
      [[ -n "$default_model" ]] && printf 'export OPENAI_DEFAULT_MODEL=%q\n' "$default_model"
    } > "$out"
    chmod 600 "$out"
    echo "wrote $out (chmod 600)"
    ;;

  claude)
    base_url="${1:?missing base-url}"; auth_token="${2:?missing api-key}"
    opus="${3:-}"; sonnet="${4:-${opus}}"; haiku="${5:-${opus}}"
    out="${SKILL_DIR}/.claude_env.local"
    {
      printf '# Auto-generated by scripts/backend.sh on %s.\n' "$(date -u +%FT%TZ)"
      printf 'export ANTHROPIC_BASE_URL=%q\n'   "$base_url"
      printf 'export ANTHROPIC_AUTH_TOKEN=%q\n' "$auth_token"
      if [[ -n "$opus" ]]; then
        printf 'export ANTHROPIC_MODEL=%q\n'                 "$opus"
        printf 'export ANTHROPIC_DEFAULT_OPUS_MODEL=%q\n'    "$opus"
        printf 'export ANTHROPIC_DEFAULT_SONNET_MODEL=%q\n'  "$sonnet"
        printf 'export ANTHROPIC_DEFAULT_HAIKU_MODEL=%q\n'   "$haiku"
        printf 'export CLAUDE_CODE_SUBAGENT_MODEL=%q\n'      "$haiku"
      fi
    } > "$out"
    chmod 600 "$out"
    echo "wrote $out (chmod 600)"
    ;;

  *)
    echo "unknown command: $cmd" >&2
    _usage >&2
    exit 2
    ;;
esac
