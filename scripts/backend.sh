#!/usr/bin/env bash
# backend.sh — Point the codex or claude actor at any OpenAI/Anthropic-compatible
# endpoint. Reads <SKILL_DIR>/models.json (user-editable, gitignored) and writes
# <SKILL_DIR>/.<actor>_env.local (chmod 600, gitignored), which {codex,claude}_turn.sh
# source before invoking the CLI.
#
# Usage:
#   backend.sh init                            # seed models.json (prints a beginner-friendly walkthrough)
#   backend.sh help-import                     # reprint the walkthrough any time
#   backend.sh apply [--no-smoke-test] [codex|claude]
#                                              # read models.json, write .<actor>_env.local for each `active` actor;
#                                              # static-checks proxy×short-alias combos, then 1-token smoke pings
#                                              # each endpoint (skip via --no-smoke-test for offline setup)
#   backend.sh validate [codex|claude]         # ping each `active` endpoint with cli_arg; fail-fast on 4xx/5xx
#                                              # WITHOUT writing env files. Use between edits to verify a config.
#   backend.sh show  [codex|claude]            # inspect current state (api_key redacted)
#   backend.sh clear <codex|claude>            # remove .<actor>_env.local
#   backend.sh codex  <base-url> <api-key> [default-model]                     # one-shot direct write (bypasses models.json)
#   backend.sh claude <base-url> <api-key> [opus-model] [sonnet-model] [haiku-model] [effort-level]
#
# Default flow (single source of truth in models.json; secret never enters chat or agent context):
#   1. backend.sh init       — creates <SKILL_DIR>/models.json + prints walkthrough
#   2. user edits models.json, replaces `_template` with their model entry
#      (4 fields: actor / cli_arg / endpoint.base_url / endpoint.api_key)
#   3. backend.sh apply      — writes the .<actor>_env.local files

set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

_usage() { sed -n '/^# backend\.sh/,/^[^#]/{ /^[^#]/d; s/^# \{0,1\}//; p; }' "$0"; }

case "${1:-}" in
  -h|--help|"") _usage; exit 0;;
esac

cmd="$1"; shift

# ── helpers ──────────────────────────────────────────────────────────────────

# Long-form import walkthrough printed by `init` (after seeding models.json) and
# by the `help-import` subcommand. Targeted at someone who has never seen this
# skill before — explains what the file is, what each field means, and gives
# three concrete copy-paste-ready examples (OpenAI / Anthropic / Anthropic-shim).
_print_import_walkthrough() {
  local mf="${SKILL_DIR}/models.json"
  cat <<EOF

──────────────────────────────────────────────────────────────────────
  HOW TO IMPORT A MODEL — first-time setup, ~2 min
──────────────────────────────────────────────────────────────────────

WHAT IS \`models.json\`?
  Your private model registry for the agent-roundtable skill. It tells
  the skill which models you have credentials for and where to send
  API requests. Stored at:
    $mf
  (chmod 600 — only you can read it; gitignored — never committed.)

THE CONTRACT
  YOU fill 4 fields per model.
  THE AGENT fills the rest (benchmarks, pricing, context window, …)
  by WebSearch on the next chat turn.

  Field      Meaning
  -----      -------
  actor      Which CLI talks to this model: "codex" or "claude"
               codex  → any OpenAI-compatible endpoint
               claude → any Anthropic-compatible endpoint
  cli_arg    The exact model id the API expects in its 'model' param
             (e.g. "gpt-5.4", "claude-opus-4-7", "deepseek-v4-pro[1m]").
             NOT your nickname for it. NOT the CLI short alias
             ("opus" / "sonnet" / "haiku" / "gpt-5"). See PROXY QUIRK below.
  base_url   The API root URL, no trailing slash.
  api_key    Your secret key.

⚠ PROXY QUIRK — read this if base_url is anything other than
  https://api.anthropic.com or https://api.openai.com :
    When you talk to OFFICIAL Anthropic / OpenAI, the CLI accepts short
    aliases ("opus", "sonnet", "gpt-5") and resolves them to a current
    dated slug. PROXIES (claude-api.org / cialloapi.cn / DeepSeek shim
    / OpenRouter / etc.) do NOT do this resolution — they reject any
    model id they don't recognise verbatim. Per claude-api.org's FAQ
    (§503 No available accounts), this is the #1 cause of 502/503:

      ❌ "opus"       (CLI alias; resolved to dated slug; rejected by proxy)
      ✅ "claude-opus-4-7"   (proxy-precise id; passes through verbatim)

    Rule of thumb: if base_url ≠ official vendor, use the EXACT model
    id from your provider's docs (claude-api.org → "claude-opus-4-7";
    cialloapi → "gpt-5.4" / "gpt-5.5"; DeepSeek → "deepseek-v4-pro[1m]").

────────────────────────────────────────────────────────
STEP 1 — open the file in your editor
────────────────────────────────────────────────────────
  \$EDITOR $mf

────────────────────────────────────────────────────────
STEP 2 — replace the \`_template\` entry under "models"
────────────────────────────────────────────────────────
  Pick the example below that matches your provider, paste it in
  place of \`_template\`, and fill in your real base_url + api_key.
  (You can keep multiple models — just give each one a unique key.)

  ── OpenAI / Azure / cialloapi / any OpenAI-compat ──
  "gpt-5": {
    "actor":   "codex",
    "cli_arg": "gpt-5",
    "endpoint": {
      "base_url": "https://api.openai.com/v1",
      "api_key":  "sk-..."
    }
  }

  ── Anthropic official ──
  "claude-opus-4-5": {
    "actor":   "claude",
    "cli_arg": "claude-opus-4-5",
    "endpoint": {
      "base_url": "https://api.anthropic.com",
      "api_key":  "sk-ant-..."
    }
  }

  ── claude-api.org (Anthropic-compat proxy, 0.7x discount) ──
  (Common CN-accessible Anthropic proxy. cli_arg + the three *_model
  fields MUST be proxy-precise dated ids — short aliases like "opus"
  cause 502/503. See https://doc.claude-api.org/channels for the
  current accepted model list.)
  "claude-opus": {
    "actor":   "claude",
    "cli_arg": "claude-opus-4-7",
    "endpoint": {
      "base_url":     "https://claude-api.org",
      "api_key":      "sk-...",
      "opus_model":   "claude-opus-4-7",
      "sonnet_model": "claude-sonnet-4-6",
      "haiku_model":  "claude-haiku-4-5"
    }
  }

  ── DeepSeek / any Anthropic-compat shim ──
  (Shims map Claude Code's opus/sonnet/haiku tiers onto upstream model
  ids that don't include 'claude'; specify each tier explicitly.)
  "deepseek-pro": {
    "actor":   "claude",
    "cli_arg": "deepseek-v4-pro[1m]",
    "endpoint": {
      "base_url":     "https://api.deepseek.com/anthropic",
      "api_key":      "sk-...",
      "opus_model":   "deepseek-v4-pro[1m]",
      "sonnet_model": "deepseek-v4-pro[1m]",
      "haiku_model":  "deepseek-v4-flash"
    }
  }

────────────────────────────────────────────────────────
STEP 3 — set \`active\` (top of the file)
────────────────────────────────────────────────────────
  Point each actor at one of your model ids:

    "active": {
      "codex":  "gpt-5",         // or null to skip codex
      "claude": "deepseek-pro"   // or null to skip claude
    }

  Leave a value as null to make that actor fall back to its own
  CLI login (\`codex login\` / \`claude auth login\`).

────────────────────────────────────────────────────────
STEP 4 — save the file, then tell the agent in chat
────────────────────────────────────────────────────────
  Just say "go" or "done". The agent will:
    1. read the non-secret fields (api_key never enters chat or context)
    2. WebSearch each new model → fill in underlying / context_window_k
       / max_output_k / benchmarks / best_for / pricing
    3. update role_defaults so route.sh can recommend your model
    4. run \`scripts/backend.sh apply\` (writes chmod-600 env files)
    5. dispatch a 1-line health-check turn to verify the endpoint
       actually answers

────────────────────────────────────────────────────────
COMMON MISTAKES
────────────────────────────────────────────────────────
  ✗ entry key starts with "_"      → skipped as placeholder
  ✗ actor is the model name        → must be exactly "codex" or "claude"
  ✗ cli_arg is your nickname       → must be the model id the API expects
  ✗ cli_arg is "opus"/"sonnet"
    /"haiku"/"gpt-5"/"gpt-4" AND
    base_url is a non-vendor proxy → see PROXY QUIRK above; \`apply\`
                                    will reject this combo with an
                                    explicit ERROR
  ✗ base_url has trailing slash    → drop it
  ✗ values still contain
    "REPLACE_WITH:*" prefixes      → fill them in or delete the entry
  ✗ apply succeeds but turns 502   → run \`backend.sh validate\` to ping
                                    the endpoint with cli_arg before
                                    paying for a real turn

────────────────────────────────────────────────────────
USEFUL COMMANDS (any time)
────────────────────────────────────────────────────────
  scripts/backend.sh show          inspect import status (key redacted)
  scripts/backend.sh apply         re-write env files after edits
                                   (runs smoke test by default; use
                                    --no-smoke-test to skip)
  scripts/backend.sh validate      ping every active endpoint with
                                   cli_arg; fail-fast on 4xx/5xx without
                                   touching env files
  scripts/backend.sh help-import   print this walkthrough again
  scripts/backend.sh clear codex   un-import an actor

──────────────────────────────────────────────────────────────────────
EOF
}

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
  python3 - "$mf" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
active = (data.get("active") or {})
models = (data.get("models") or {})

# ── Header ────────────────────────────────────────────────────────────────
suffix = "" if p.name == "models.json" else f"  (fallback: {p.name})"
print(f"=== Actor import status{suffix} ===")
def _is_placeholder(v):
    return isinstance(v, str) and v.startswith("REPLACE_WITH")

for actor in ("codex", "claude"):
    mid = active.get(actor)
    if not mid:
        print(f"  {actor:<7}  ❌ NOT IMPORTED   active.{actor} is null — CLI will use its own login")
        continue
    if mid.startswith("_"):
        print(f"  {actor:<7}  ⚠  PLACEHOLDER    active.{actor}={mid!r} — rename this entry to a real model id")
        continue
    m = models.get(mid)
    if not m:
        print(f"  {actor:<7}  ⚠  BROKEN         active.{actor}={mid!r} but no such entry in `models`")
        continue
    ep = m.get("endpoint") or {}
    base, key = ep.get("base_url", ""), ep.get("api_key", "")
    key_ref = ep.get("api_key_ref", "")
    cli = m.get("cli_arg", mid)
    if _is_placeholder(base) or _is_placeholder(key) or _is_placeholder(m.get("actor", "")):
        print(f"  {actor:<7}  ⚠  PLACEHOLDER    model={mid!r} still has REPLACE_WITH:* fields — fill them in")
        continue
    has_key = bool(key or key_ref)
    if base and has_key:
        print(f"  {actor:<7}  ✅ IMPORTED       model={mid!r}  cli_arg={cli!r}")
        print(f"           {'':<17}base_url={base}")
    else:
        missing = [lbl for lbl, v in (("base_url", base), ("api_key/api_key_ref", has_key)) if not v]
        print(f"  {actor:<7}  ⚠  INCOMPLETE     model={mid!r} — endpoint missing: {','.join(missing) or 'whole block'}")

# ── Catalog table ────────────────────────────────────────────────────────
print()
print(f"=== Catalog ({len(models)} entries) ===")
if not models:
    print("  (empty)")
else:
    rows = []
    for mid, m in models.items():
        actor = m.get("actor", "?")
        cli   = str(m.get("cli_arg") or mid)
        if mid.startswith("_") or _is_placeholder(actor):
            ep_status = "⚠ PLACEHOLDER (fill in or delete)"
        elif actor == "cursor-subagent":
            ep_status = "via Cursor IDE"
        else:
            ep = m.get("endpoint") or {}
            base, key = ep.get("base_url", ""), ep.get("api_key", "")
            key_ref = ep.get("api_key_ref", "")
            if _is_placeholder(base) or _is_placeholder(key):
                ep_status = "⚠ PLACEHOLDER (fill in)"
            elif base and (key or key_ref):
                ep_status = "endpoint set"
            elif ep:
                ep_status = "endpoint partial"
            else:
                ep_status = "no endpoint"
        rows.append((mid, actor, cli, ep_status))
    w_id    = max(len(r[0]) for r in rows)
    w_actor = max(len(r[1]) for r in rows)
    w_cli   = max(len(r[2]) for r in rows)
    for mid, actor, cli, ep_status in rows:
        marker = "★" if mid in (active.get("codex"), active.get("claude")) else " "
        print(f"  {marker} {mid:<{w_id}}  actor={actor:<{w_actor}}  cli_arg={cli:<{w_cli}}  {ep_status}")
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
    echo "✓ wrote $dst (chmod 600)"
    _print_import_walkthrough
    ;;

  help-import|help)
    _print_import_walkthrough
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
      # First-time-user hint: surfaced when models.json has no real entries
      # (i.e. user is still on the shipped catalog with the _template
      # placeholder unedited and no codex/claude entry credentialed).
      mf="$(_models_file)"
      if python3 -c "
import json, sys
d = json.load(open('$mf'))
real = [
  k for k, m in (d.get('models') or {}).items()
  if not k.startswith('_')
  and isinstance(m, dict)
  and ((m.get('endpoint') or {}).get('api_key', '').strip()
       or (m.get('endpoint') or {}).get('api_key_ref', '').strip())
  and not (m.get('endpoint') or {}).get('api_key', '').startswith('REPLACE_WITH')
]
sys.exit(0 if not real else 1)
" 2>/dev/null; then
        cat <<'HINT'

────────────────────────────────────────────────────────
  No imported models yet. Run:
    scripts/backend.sh help-import
  for a step-by-step walkthrough on how to add one.
────────────────────────────────────────────────────────
HINT
      fi
    fi
    ;;

  clear)
    actor="${1:?which actor: codex|claude}"
    rm -f "${SKILL_DIR}/.${actor}_env.local"
    echo "cleared ${SKILL_DIR}/.${actor}_env.local"
    ;;

  apply)
    smoke_flag="run"; only=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --no-smoke-test|--no-smoke) smoke_flag="skip"; shift;;
        codex|claude)               only="$1"; shift;;
        --) shift; break;;
        -*) echo "ERROR: unknown apply option: $1" >&2; exit 2;;
        *)  only="$1"; shift;;
      esac
    done
    mf="${SKILL_DIR}/models.json"
    [[ -r "$mf" ]] || { echo "ERROR: $mf not found. Run: $0 init" >&2; exit 2; }
    python3 - "$mf" "$0" "$only" "$smoke_flag" <<'PY'
import json, sys, subprocess, pathlib, urllib.parse
mf, script, only, smoke_flag = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
data = json.loads(pathlib.Path(mf).read_text())
active = data.get("active") or {}
models = data.get("models") or {}
targets = [only] if only else ["codex", "claude"]
applied = 0
# Track {actor: (base_url, key, cli_arg, claude_extras_or_None)} for post-apply smoke test.
smoked: list = []

# === Static check: known proxy host × known CLI short alias = ERROR ==========
# Why: proxies (claude-api.org / cialloapi / DeepSeek-shim / OpenRouter) do not
# resolve CLI aliases like "opus" / "gpt-5" to dated slugs the way the OFFICIAL
# vendor APIs do. Sending a short alias to a proxy returns 502/503 with bodies
# like "No available accounts" — the #1 setup failure mode (claude-api.org FAQ
# §503). Catching it here saves the user a 600s real-turn 502.
PROXY_RULES = {
    "claude-api.org":   {"aliases": {"opus", "sonnet", "haiku"},
                         "doc": "https://doc.claude-api.org/channels"},
    "cialloapi.cn":     {"aliases": {"gpt-5", "gpt-4", "o1", "o3"},
                         "doc": "https://cialloapi.cn dashboard (model list)"},
    "api.deepseek.com": {"aliases": {"opus", "sonnet", "haiku"},
                         "doc": "https://api-docs.deepseek.com/"},
    "openrouter.ai":    {"aliases": {"opus", "sonnet", "haiku",
                                     "gpt-5", "gpt-4", "o1", "o3"},
                         "doc": "https://openrouter.ai/models"},
}
def _violations(base_url: str, cli_arg: str, *, label: str = "cli_arg"):
    """Yield (proxy_host, doc_url, label) for each rule violated by this pair."""
    if not base_url or not cli_arg:
        return
    host = urllib.parse.urlparse(base_url).hostname or ""
    for proxy_host, rule in PROXY_RULES.items():
        if proxy_host in host and cli_arg in rule["aliases"]:
            yield (proxy_host, rule["doc"], label)
            return  # one match per pair is enough
# =============================================================================

# === C. SMOKE TEST: minimal 1-token ping per actor ==========================
# Why: catches ALL endpoint failures the static check misses — base_url typos,
# expired keys, model id not in vendor's accepted list, transient 5xx, DNS
# breakage. Fail-fast in seconds instead of after a 600s real turn. Uses stdlib
# urllib only (no curl dep). Short timeout (15s) so a hung proxy doesn't block
# setup.
import urllib.request
import urllib.error
SMOKE_TIMEOUT_S = 15
# Many proxies sit behind Cloudflare with default-deny rules that filter on
# User-Agent (stdlib urllib's default 'Python-urllib/3.x' triggers CF code 1010
# Forbidden). We send a curl-shaped UA — proxies invariably whitelist curl.
SMOKE_UA = "curl/8.4.0 agent-roundtable-validator"
def _smoke_codex(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """Return (ok, message). OpenAI-compatible /chat/completions."""
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}],
                       "max_tokens": 1, "stream": False}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": SMOKE_UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=SMOKE_TIMEOUT_S) as r:
            return True, f"HTTP {r.status} (model accepted)"
    except urllib.error.HTTPError as e:
        body_preview = (e.read() or b"").decode("utf-8", "replace")[:500]
        return False, f"HTTP {e.code} {e.reason} — body[:500]={body_preview!r}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e!r}"
def _smoke_claude(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """Return (ok, message). Anthropic-compatible /v1/messages.
    Uses Bearer + anthropic-version header — works against official Anthropic
    AND known Anthropic-compat proxies (claude-api.org, DeepSeek-shim).
    """
    url = base_url.rstrip("/") + "/v1/messages"
    body = json.dumps({"model": model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ping"}]}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,                # official Anthropic prefers this
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": SMOKE_UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=SMOKE_TIMEOUT_S) as r:
            return True, f"HTTP {r.status} (model accepted)"
    except urllib.error.HTTPError as e:
        body_preview = (e.read() or b"").decode("utf-8", "replace")[:500]
        return False, f"HTTP {e.code} {e.reason} — body[:500]={body_preview!r}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e!r}"
def _run_smoke(actor: str, base: str, key: str, cli_arg: str, claude_extras) -> bool:
    """Smoke-test one actor; return True if all checks pass."""
    print(f"SMOKE {actor}: ping {base!r} model={cli_arg!r} ... ", end="", flush=True)
    if actor == "codex":
        ok, msg = _smoke_codex(base, key, cli_arg)
    else:
        ok, msg = _smoke_claude(base, key, cli_arg)
    print("OK" if ok else "FAIL")
    print(f"  → {msg}")
    if not ok:
        return False
    # For claude: also verify opus/sonnet/haiku tier models if they differ.
    if actor == "claude" and claude_extras:
        op, son, hai = claude_extras
        seen = {cli_arg}
        for label, mid in [("opus_model", op), ("sonnet_model", son), ("haiku_model", hai)]:
            if mid in seen or not mid:
                continue
            seen.add(mid)
            print(f"SMOKE {actor}: ping {base!r} {label}={mid!r} ... ", end="", flush=True)
            ok2, msg2 = _smoke_claude(base, key, mid)
            print("OK" if ok2 else "FAIL")
            print(f"  → {msg2}")
            if not ok2:
                return False
    return True
# =============================================================================
for actor in targets:
    if actor not in ("codex", "claude"):
        print(f"ERROR: unknown actor {actor!r}", file=sys.stderr); sys.exit(2)
    mid = active.get(actor)
    if not mid:
        print(f"SKIP {actor}: active.{actor} is null in models.json", file=sys.stderr); continue
    if mid.startswith("_"):
        print(f"SKIP {actor}: active.{actor}={mid!r} is a placeholder (keys starting with _ are skipped). Replace _template with a real model id.", file=sys.stderr); continue
    m = models.get(mid)
    if not m:
        print(f"ERROR {actor}: active.{actor} = {mid!r} but no such entry in models block", file=sys.stderr); sys.exit(2)
    declared_actor = m.get("actor", "")
    if declared_actor.startswith("REPLACE_WITH"):
        print(f"SKIP {actor}: model {mid!r} still has placeholder values (actor={declared_actor!r}). Fill in actor/cli_arg/endpoint first.", file=sys.stderr); continue
    if declared_actor and declared_actor != actor:
        print(f"WARN  {actor}: model {mid!r} is registered as actor={declared_actor!r}", file=sys.stderr)
    ep = m.get("endpoint") or {}
    base, key = ep.get("base_url", ""), ep.get("api_key", "")
    key_ref = ep.get("api_key_ref", "")
    if base.startswith("REPLACE_WITH") or key.startswith("REPLACE_WITH"):
        print(f"SKIP {actor}: model {mid!r} endpoint still has REPLACE_WITH:* placeholder values.", file=sys.stderr); continue
    if key_ref:
        if not key_ref.startswith("secrets:"):
            print(f"ERROR: api_key_ref={key_ref!r} is not a 'secrets:' reference", file=sys.stderr); sys.exit(2)
        rest = key_ref[len("secrets:"):]
        # Split from the RIGHT — model_ids may contain dots (e.g. gpt-5.5)
        parts = rest.rsplit(".", 1)
        if len(parts) != 2:
            print(f"ERROR: api_key_ref={key_ref!r} malformed; expected 'secrets:<model_id>.<key>'", file=sys.stderr); sys.exit(2)
        ref_model_id, ref_key_name = parts
        secrets_path = pathlib.Path(mf).parent / "models.secrets.json"
        if not secrets_path.exists():
            print(f"ERROR: api_key_ref points to {key_ref!r} but models.secrets.json missing/incomplete. Run 'backend.sh init' or create models.secrets.json manually.", file=sys.stderr); sys.exit(2)
        try:
            secrets = json.loads(secrets_path.read_text())
        except Exception as e:
            print(f"ERROR: failed to parse models.secrets.json: {e}", file=sys.stderr); sys.exit(2)
        key = (secrets.get(ref_model_id) or {}).get(ref_key_name, "")
        if not key:
            print(f"ERROR: api_key_ref points to {key_ref!r} but models.secrets.json missing/incomplete. Run 'backend.sh init' or create models.secrets.json manually.", file=sys.stderr); sys.exit(2)
    elif key:
        print(f"WARN [backend.sh]: endpoint.api_key in models.json is deprecated; move to models.secrets.json.", file=sys.stderr)
    if not base or not key:
        print(f"SKIP {actor}: model {mid!r} has no endpoint.base_url or api_key set", file=sys.stderr); continue
    cli_arg = m.get("cli_arg", mid)
    if actor == "claude":
        op_model = ep.get("opus_model") or ep.get("claude_opus_model") or cli_arg
        son_model = ep.get("sonnet_model") or ep.get("claude_sonnet_model") or op_model
        hai_model = ep.get("haiku_model") or ep.get("claude_haiku_model") or son_model
        effort = ep.get("claude_effort_level") or ep.get("effort_level") or ""
        cmd = [script, actor, base, key, op_model, son_model, hai_model, effort]
    else:
        cmd = [script, actor, base, key, cli_arg]
    # ── B. STATIC CHECK: known proxy host × known short alias ────────────────
    # Run BEFORE any subprocess write — fail-fast keeps the env file in its
    # last-known-good state instead of overwriting it with a broken combo.
    static_errs = list(_violations(base, cli_arg, label="cli_arg"))
    if actor == "claude":
        static_errs += list(_violations(base, op_model, label="opus_model"))
        static_errs += list(_violations(base, son_model, label="sonnet_model"))
        static_errs += list(_violations(base, hai_model, label="haiku_model"))
    if static_errs:
        print(f"ERROR {actor}: model={mid!r} fails static check — base_url is a known proxy that requires exact model ids:", file=sys.stderr)
        for proxy_host, doc, label in static_errs:
            bad_val = {"cli_arg": cli_arg, "opus_model": op_model if actor == "claude" else "",
                       "sonnet_model": son_model if actor == "claude" else "",
                       "haiku_model": hai_model if actor == "claude" else ""}.get(label, "?")
            print(f"  • endpoint.{label}={bad_val!r} is a CLI short alias rejected by {proxy_host}. Replace with a proxy-precise dated id from {doc}.", file=sys.stderr)
        print(f"  Hint: see `backend.sh help-import` PROXY QUIRK section, or skills/roundtable-setup/SKILL.md §Provider quirks.", file=sys.stderr)
        sys.exit(2)
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        sys.exit(r.returncode)
    applied += 1
    smoked.append((actor, base, key, cli_arg,
                   (op_model, son_model, hai_model) if actor == "claude" else None))
    if actor == "claude":
        eff = ep.get("claude_effort_level") or ep.get("effort_level") or ""
        print(
            "APPLIED actor="
            + actor
            + f" model={mid!r} cli_arg_for_alias={cli_arg!r}"
            + f" anthropic_models=({op_model!r},{son_model!r},{hai_model!r})"
            + f" base_url={base}"
            + (f" effort={eff!r}" if eff else "")
        )
    else:
        print(f"APPLIED actor={actor} model={mid!r} cli_arg={cli_arg!r} base_url={base}")
if applied == 0:
    print("Nothing applied. Edit models.json: set `active.{codex,claude}` to a model id whose entry has an `endpoint` block with both base_url and api_key.", file=sys.stderr)
    sys.exit(2)
# ── C. SMOKE TEST: ping each freshly-applied endpoint ───────────────────────
if smoke_flag == "skip":
    print("(smoke test skipped: --no-smoke-test)")
else:
    print("--- smoke test (1-token ping per actor; --no-smoke-test to skip) ---")
    smoke_failed = []
    for actor, base, key, cli_arg, claude_extras in smoked:
        if not _run_smoke(actor, base, key, cli_arg, claude_extras):
            smoke_failed.append(actor)
    if smoke_failed:
        print(f"ERROR: smoke test FAILED for: {','.join(smoke_failed)}.", file=sys.stderr)
        print("  The .{actor}_env.local file IS written (apply already returned), but the endpoint did", file=sys.stderr)
        print("  not accept a 1-token ping with these credentials + cli_arg. Common causes:", file=sys.stderr)
        print("    - cli_arg is not in the proxy's accepted-model list (check vendor doc)", file=sys.stderr)
        print("    - base_url has a typo or wrong path (e.g. needs /v1)", file=sys.stderr)
        print("    - api_key is expired, wrong-channel, or out of credits", file=sys.stderr)
        print("    - proxy is temporarily down (re-run `backend.sh validate` in a few minutes)", file=sys.stderr)
        sys.exit(3)
    print("--- smoke test: all OK ---")
PY
    ;;

  validate)
    mf="${SKILL_DIR}/models.json"
    [[ -r "$mf" ]] || { echo "ERROR: $mf not found. Run: $0 init" >&2; exit 2; }
    only="${1:-}"
    python3 - "$mf" "$only" <<'PY'
"""validate — read models.json, ping each `active` actor's endpoint with its
cli_arg, fail-fast on 4xx/5xx. Does NOT touch .codex_env.local / .claude_env.local
— this is the dry-run path users invoke between edits to confirm a config
without overwriting their last-known-good env files."""
import json, sys, pathlib, urllib.parse, urllib.request, urllib.error
mf, only = sys.argv[1], sys.argv[2]
data = json.loads(pathlib.Path(mf).read_text())
active = data.get("active") or {}
models = data.get("models") or {}
targets = [only] if only else ["codex", "claude"]
SMOKE_TIMEOUT_S = 15
SMOKE_UA = "curl/8.4.0 agent-roundtable-validator"
def _smoke(actor, base, key, model):
    base = base.rstrip("/")
    if actor == "codex":
        url = base + "/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1, "stream": False}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                   "User-Agent": SMOKE_UA}
    else:
        url = base + "/v1/messages"
        body = {"model": model, "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}]}
        headers = {"Authorization": f"Bearer {key}", "x-api-key": key,
                   "anthropic-version": "2023-06-01", "Content-Type": "application/json",
                   "User-Agent": SMOKE_UA}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=SMOKE_TIMEOUT_S) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        body_preview = (e.read() or b"").decode("utf-8", "replace")[:500]
        return False, f"HTTP {e.code} {e.reason} — {body_preview!r}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e!r}"
fails = []
for actor in targets:
    if actor not in ("codex", "claude"):
        print(f"ERROR: unknown actor {actor!r}", file=sys.stderr); sys.exit(2)
    mid = active.get(actor)
    if not mid or mid.startswith("_"):
        print(f"SKIP {actor}: active.{actor}={mid!r}"); continue
    m = models.get(mid) or {}
    ep = m.get("endpoint") or {}
    base, key = ep.get("base_url", ""), ep.get("api_key", "")
    cli_arg = m.get("cli_arg") or mid
    if not base or not key:
        # Try secrets.json for api_key_ref
        ref = ep.get("api_key_ref", "")
        if ref.startswith("secrets:"):
            sp = pathlib.Path(mf).parent / "models.secrets.json"
            if sp.exists():
                rest = ref[len("secrets:"):]
                parts = rest.rsplit(".", 1)
                if len(parts) == 2:
                    sec = json.loads(sp.read_text())
                    key = (sec.get(parts[0]) or {}).get(parts[1], "")
        if not base or not key:
            print(f"SKIP {actor}: model={mid!r} missing base_url or api_key"); continue
    print(f"VALIDATE {actor}: {base!r} model={cli_arg!r} ... ", end="", flush=True)
    ok, msg = _smoke(actor, base, key, cli_arg)
    print("OK" if ok else "FAIL")
    print(f"  → {msg}")
    if not ok:
        fails.append(actor)
    if actor == "claude":
        op = ep.get("opus_model") or ep.get("claude_opus_model") or cli_arg
        son = ep.get("sonnet_model") or ep.get("claude_sonnet_model") or op
        hai = ep.get("haiku_model") or ep.get("claude_haiku_model") or son
        seen = {cli_arg}
        for label, mm in [("opus_model", op), ("sonnet_model", son), ("haiku_model", hai)]:
            if mm in seen or not mm:
                continue
            seen.add(mm)
            print(f"VALIDATE {actor}: {base!r} {label}={mm!r} ... ", end="", flush=True)
            ok2, msg2 = _smoke(actor, base, key, mm)
            print("OK" if ok2 else "FAIL")
            print(f"  → {msg2}")
            if not ok2 and actor not in fails:
                fails.append(actor)
if fails:
    print(f"FAIL: {','.join(fails)}", file=sys.stderr)
    sys.exit(3)
print("--- validate: all OK ---")
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
    effort="${6:-}"
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
      [[ -n "$effort" ]] && printf 'export CLAUDE_CODE_EFFORT_LEVEL=%q\n' "$effort"
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
