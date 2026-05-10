#!/usr/bin/env python3
"""Registry helper utilities for backend.sh subcommands."""
import json
import pathlib
import sys

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]


def show_models_summary(registry_path=None):
    """Print a formatted summary of models.json."""
    if registry_path is None:
        registry_path = _SKILL_DIR / "models.json"
        if not registry_path.exists():
            registry_path = _SKILL_DIR / "models.example.json"

    p = pathlib.Path(registry_path)
    data = json.loads(p.read_text())
    active = (data.get("active") or {})
    models = (data.get("models") or {})

    # Load sibling models.secrets.json (chmod 600, gitignored) for endpoint detection.
    # Joined by exact model_id — see apply block for rationale.
    _secrets = {}
    _secrets_path = p.parent / "models.secrets.json"
    if _secrets_path.exists():
        try:
            _secrets = json.loads(_secrets_path.read_text())
        except Exception:
            _secrets = {}

    # ── Header ────────────────────────────────────────────────────────────────
    suffix = "" if p.name == "models.json" else f"  (fallback: {p.name})"
    print(f"=== Actor import status{suffix} ===")

    # ── network_proxy state ───────────────────────────────────────────────────
    proxy = data.get("network_proxy") or {}

    def _redact(url: str) -> str:
        # IP-only hosts (typical for private proxies) are info, not secret.
        return url or "(unset)"

    if not proxy:
        print("  proxy    \u26aa NOT CONFIGURED  (add `network_proxy` block to enable)")
    elif not proxy.get("enabled"):
        print("  proxy    \u26aa DISABLED        (network_proxy.enabled=false \u2014 direct connection)")
    elif (proxy.get("http_proxy", "")).startswith("REPLACE_WITH"):
        print("  proxy    \u26a0  PLACEHOLDER     (replace REPLACE_WITH:* in network_proxy or set enabled=false)")
    else:
        print(f"  proxy    \u2705 ENABLED         http={_redact(proxy.get('http_proxy', ''))}  "
              f"https={_redact(proxy.get('https_proxy', ''))}")
        if proxy.get("speedup_observed"):
            print(f"           {'': <17}{proxy['speedup_observed']}")
    print()

    def _is_placeholder(v):
        return isinstance(v, str) and v.startswith("REPLACE_WITH")

    for actor in ("codex", "claude"):
        mid = active.get(actor)
        if not mid:
            print(f"  {actor:<7}  \u274c NOT IMPORTED   active.{actor} is null \u2014 CLI will use its own login")
            continue
        if mid.startswith("_"):
            print(f"  {actor:<7}  \u26a0  PLACEHOLDER    active.{actor}={mid!r} \u2014 rename this entry to a real model id")
            continue
        m = models.get(mid)
        if not m:
            print(f"  {actor:<7}  \u26a0  BROKEN         active.{actor}={mid!r} but no such entry in `models`")
            continue
        ep = m.get("endpoint") or {}
        base, key = ep.get("base_url", ""), ep.get("api_key", "")
        cli = m.get("cli_arg", mid)
        sec_key = (_secrets.get(mid) or {}).get("api_key", "")
        if _is_placeholder(base) or _is_placeholder(key) or _is_placeholder(m.get("actor", "")):
            print(f"  {actor:<7}  \u26a0  PLACEHOLDER    model={mid!r} still has REPLACE_WITH:* fields \u2014 fill them in")
            continue
        has_key = bool(key or sec_key)
        if base and has_key:
            print(f"  {actor:<7}  \u2705 IMPORTED       model={mid!r}  cli_arg={cli!r}")
            print(f"           {'': <17}base_url={base}")
        else:
            missing = [
                lbl for lbl, v in (
                    ("base_url", base),
                    ("api_key (in models.json or models.secrets.json)", has_key),
                )
                if not v
            ]
            print(f"  {actor:<7}  \u26a0  INCOMPLETE     model={mid!r} \u2014 endpoint missing: "
                  f"{','.join(missing) or 'whole block'}")

    # ── Catalog table ─────────────────────────────────────────────────────────
    print()
    print(f"=== Catalog ({len(models)} entries) ===")
    if not models:
        print("  (empty)")
    else:
        rows = []
        for mid, m in models.items():
            actor = m.get("actor", "?")
            cli = str(m.get("cli_arg") or mid)
            if mid.startswith("_") or _is_placeholder(actor):
                ep_status = "\u26a0 PLACEHOLDER (fill in or delete)"
            elif actor == "cursor-subagent":
                ep_status = "via Cursor IDE"
            else:
                ep = m.get("endpoint") or {}
                base, key = ep.get("base_url", ""), ep.get("api_key", "")
                sec_key = (_secrets.get(mid) or {}).get("api_key", "")
                if _is_placeholder(base) or _is_placeholder(key):
                    ep_status = "\u26a0 PLACEHOLDER (fill in)"
                elif base and (key or sec_key):
                    ep_status = "endpoint set"
                elif ep:
                    ep_status = "endpoint partial"
                else:
                    ep_status = "no endpoint"
            rows.append((mid, actor, cli, ep_status))
        w_id = max(len(r[0]) for r in rows)
        w_actor = max(len(r[1]) for r in rows)
        w_cli = max(len(r[2]) for r in rows)
        for mid, actor, cli, ep_status in rows:
            marker = "\u2605" if mid in (active.get("codex"), active.get("claude")) else " "
            print(f"  {marker} {mid:<{w_id}}  actor={actor:<{w_actor}}  cli_arg={cli:<{w_cli}}  {ep_status}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        show_models_summary()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
