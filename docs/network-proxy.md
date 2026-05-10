# Network Proxy

> Reference for `roundtable-setup`. Optional; skip if you have direct API access.

`models.json` accepts a top-level `network_proxy` block. Example:

```json
"network_proxy": {
  "enabled": true,
  "http_proxy":  "http://192.168.32.28:18000",
  "https_proxy": "http://192.168.32.28:18000",
  "no_proxy":    "localhost,127.0.0.1"
}
```

What it does:

- **`apply` / `validate`** read the block and set `https_proxy` in their own Python process before pinging endpoints — so the smoke test verifies what real turns will see, not a different network path.
- **`apply`** also appends the same `export` lines to `.codex_env.local` / `.claude_env.local`. Turn scripts (`codex_turn.sh`, `claude_turn.sh`) source those files at dispatch, so Codex/Claude CLIs and `speed_test.py` automatically inherit the proxy.
- **`show`** surfaces proxy state (✅ ENABLED / ⚪ DISABLED / ⚠ PLACEHOLDER) at the top of its output.

What it does **not** do:

- It does **not** affect the cursor-subagent dispatch path (Cursor IDE manages its own network — proxy must be configured in Cursor settings if needed).
- It does **not** touch the user's shell. Only the turn scripts and validation tools, and only when sourcing the actor env files.

When to use:

- API access from a network where direct routes are slow / blocked (e.g. observed +30–47% tokens/sec on cialloapi.cn and claude-api.org via a corporate proxy).
- After enabling, run `python3 scripts/lib/speed_test.py` against your active models to refresh `endpoint.speed.tokens_per_sec_median` — the route.py / estimate_cost.py decisions depend on these numbers.

When to leave it off:

- Direct connection is already fast (vendor-direct `api.anthropic.com` / `api.openai.com` from US/EU networks).
- You don't trust the proxy to see your API keys (it does — they pass through the `Authorization` header). Use only proxies you trust at the same level as the API endpoint itself.
