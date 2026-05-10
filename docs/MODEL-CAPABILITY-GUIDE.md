# Model Capability Guide

> How to get the best out of each actor and avoid common pitfalls.  
> See `models.json` for current registry; `models.example.json` for full catalog.

---

## Actors at a glance

| Actor | Best at | Watch out for |
|-------|---------|---------------|
| **Codex CLI** (`codex`) | Repo-grounded execution; structured JSONL trace; goal bridge (`get_goal` / `create_goal` / `update_goal`) built-ins | Default timeout 1800s may cut very long reasoning chains; final message **must be only** the five-part turn body |
| **Claude CLI** (`claude`) | Careful review with constrained tools; `plan` permission mode for read-only reviewer roles; `--bare` for isolation | Default timeout 1500s; Anthropic-compat shims (e.g. DeepSeek) can have long tail latency; tool allowlist may block a legitimate read-only command |
| **Cursor subagent** (`cursor-subagent`) | Any Cursor-billed model (Gemini, Sonnet, Opus, Composer); highest SWE-bench scores available; good aggregator | No timeout cap in skill; Cursor task queue latency unbounded; prompts must be **fully self-contained** (no shared chat history) |

---

## Model registry (shipped defaults from `models.example.json`)

The aliases below ship in `models.example.json`. Any user can swap them for their own
BYOK aliases — the registry is the source of truth, this table is illustrative.

| Alias | Actor | Underlying | Context | Best for |
|-------|-------|-----------|---------|---------|
| `gpt-5.5` | codex | OpenAI GPT-5.5 (Apr 2026) | 1M tok | Codex-side executor / planner |
| `gpt-5.3-codex` | codex | OpenAI GPT-5.3-Codex (Feb 2026) | 400K tok | Cheaper Codex executor; terminal-heavy tasks |
| `claude-4.7-opus` | claude | Anthropic Claude Opus 4.7 (Apr 2026) | 1M tok | Highest-rigor reviewer (SWE-Pro leader) |
| `claude-4.6-sonnet` | claude | Anthropic Claude Sonnet 4.6 (Feb 2026) | 1M tok | Balanced executor / discussant |
| `cursor-composer-2` | cursor-subagent | Cursor Composer 2 | 200K tok | Cheap parallel executor; doc/code fan-out |
| `cursor-claude-4.7-opus` | cursor-subagent | Claude Opus 4.7 (thinking-high) | 1M tok | Reviewer-aggregator; hardest reviewer |
| `cursor-claude-4.6-sonnet` | cursor-subagent | Claude Sonnet 4.6 (thinking-medium) | 1M tok | Reviewer; executor-heavy |
| `cursor-gemini-3.1-pro` | cursor-subagent | Gemini 3.1 Pro | 1M tok | Cross-vendor third opinion; ARC-AGI / scientific QA |

Speak in alias *categories* when writing prompts — "your Codex executor alias", "your
reviewer-aggregator alias" — and let the registry resolve to a concrete name.

---

## Geography & vendor risk distribution

The three actor families have overlapping but non-identical geo-accessibility
profiles. Understanding this lets you build a topology that stays operational
even when one access path is disrupted.

| Actor family | Dispatch mechanism | CN (no VPN) | US/EU enterprise |
|---|---|---|---|
| `codex` | Codex CLI → cialloapi proxy (`cialloapi.cn/v1`) | ✓ stable | ✓ (proxy, re-check rate limits) |
| `claude` | Claude CLI → DeepSeek Anthropic-compat (`api.deepseek.com/anthropic`) | ✓ stable | ✓ (verify data-residency policy) |
| `cursor-subagent` | Cursor IDE billing (`cursor.com/cn/docs/models-and-pricing`) | ✓ CN subdomain stable | ✓ |

**Key point for CN environments.** OpenAI's direct API (`api.openai.com`) is
blocked by the Great Firewall; the `codex` actor routes through `cialloapi.cn`
to remain accessible.  DeepSeek's API is CN-domestically hosted and accessible
without a proxy.  Cursor billing uses a CN-specific subdomain.  As a result,
all three roundtable actor families are reachable from within CN simultaneously
— this is intentional, not accidental.

### Failover opt-in

By default, roundtable does **not** automatically switch to a fallback model
when a turn fails (`failover_policy.enabled = false` in `models.json`).  To
enable automatic failover on rate-limit, timeout, or stall:

**Step 1** — Edit `models.json`:

```json
"failover_policy": {
  "enabled": true,
  …
}
```

**Step 2** — Export the opt-in flag before dispatch:

```bash
export ROUNDTABLE_FAILOVER_OPT_IN=1
bash scripts/codex_turn.sh <slug> --role executor -m gpt-5.5
```

When enabled, `_common.sh:dispatch_with_fallback` walks each model's
`fallback_chain` on trigger events (`rate-limit`, `timeout-exceeded-budget`,
`convergence-loop-stalled-2x`) and requires user consent before the first
failover in any thread.  Each failover hop is logged to
`<thread_dir>/THREAD_LEDGER.md`.

**Cross-family failover.** The default `fallback_chain` entries in
`models.json` stay within the same vendor family (e.g. `gpt-5.5 → gpt-5.4 →
gpt-5.4-mini`).  For true cross-vendor geo-redundancy — e.g. if cialloapi is
unreachable — extend the chain manually:

```json
"gpt-5.5": {
  "fallback_chain": ["gpt-5.4", "claude-opus"]
}
```

This causes `codex_turn.sh` to fall back to the `claude` actor (DeepSeek,
CN-stable) when both OpenAI aliases are unavailable.

---

## Writing effective prompts

### 1. Put ground truth in `GOAL.md`, not the addendum

`GOAL.md` is injected into every turn. Put objective criteria, verification commands, and scope there. Use `--addendum` for turn-specific deltas only.

### 2. The five-part turn body must be the **entire** final message

The chat parent appends this block verbatim to `THREAD.md` after the
`## Turn N — <actor> / <role> — <ts>` header (which the script writes for you):

```
**Read**: <files opened — abs path + line range>
**Did**: <what was done, bulleted>
**Verification**: <commands + outcomes; reviewer JSON verdict goes here>
**Open questions**: <new ambiguities>
**Hand-off**: <accept | revise: <who> on <what> | escalate-to-user: <q>>
```

Any preamble before this block breaks `append_turn.sh` parsing.

### 3. Reviewers: put JSON first in Verification

`extract_json_verdict` greps for the first ` ```json ` block inside `**Verification**`. If the JSON is preceded by prose, extraction may fail silently.

### 4. Use workspace-absolute paths for addendum files

In Cursor sandboxes, `/tmp` paths may be inaccessible to the script. Use `--addendum-file /full/path/to/file`.

---

## Multi-agent patterns

### Blind parallel review (anti-sycophancy)

Use `--blind` on all parallel reviewers. This suppresses the prior verdict from their prompt, reducing the 85% modal adoption rate observed when reviewers see a prior strong verdict.

```bash
# Parallel blind reviewers (run via two separate Shell tool calls in one
# message — see docs/advanced.md "Parallel dispatch")
bash scripts/codex_turn.sh  SLUG --role reviewer -m <your-codex-alias>  --blind
bash scripts/claude_turn.sh SLUG --role reviewer --model <your-claude-alias> --blind
# Aggregator sees all verdicts (no --blind)
bash scripts/codex_turn.sh SLUG --role reviewer-aggregator -m <your-aggregator-alias>
```

**Do NOT use `--blind` on the aggregator** — it needs to see all verdicts to select the most defensible one.

### Cheap companion alongside expensive dispatch (Principle A)

When dispatching a mid-tier or expensive model, always run a cheap cross-vendor companion in parallel for the same role. The companion uses `--blind`.

```bash
# Expensive primary (one Shell tool call)
bash scripts/codex_turn.sh  SLUG --role executor -m <your-codex-alias>
# Cheap cross-vendor companion, blind (a second Shell tool call in the same message)
bash scripts/claude_turn.sh SLUG --role reviewer --model <your-claude-alias> --blind
```

Disagreement between the two is a quality signal — surface it to the user; do not discard it.

**Skip for:** trivial tasks (single file read, typo fix). Use for: any execution with side effects or significant scope.

### Devil's advocate

Use when consensus is suspicious or stakes are high. Assign to a cheap model (cost-efficient adversarial coverage).

```bash
bash scripts/claude_turn.sh SLUG --role devils-advocate --model <your-cheap-claude-alias> --blind
```

`codex_turn.sh`, `claude_turn.sh`, and `append_turn.sh` all extract the JSON verdict for `devils-advocate` (same path as `reviewer`).

### Independent verification (Principle B)

Every agent must read source files and run commands **before** consulting `THREAD.md`. `THREAD.md` is context (a log), not evidence. Prior agents' summaries may be biased by their model family.

Put verification commands in `GOAL.md`:

```markdown
## Verification commands
```bash
bash -n scripts/_common.sh && echo "OK"
grep -n "pattern" file.sh
wc -l SKILL.md
```
```

---

## Constraints to remember

| Constraint | Source | Impact |
|-----------|--------|--------|
| `disable-model-invocation: true` | `SKILL.md` | Parent must orchestrate; skill doesn't auto-call models |
| Five-part output required | Role system prompts | Preamble breaks thread append |
| `reviewer.schema.json` strict (`additionalProperties: false`) | Schema | Extra JSON keys fail downstream extraction |
| Verification truncation ~1000 chars | `compact_recent_turns.py` | Long command output truncated in injected context |
| Compaction strips `**Read**` | `compact_thread.py` | Evidence chains lost after compaction |
| `--latency fast` removes cursor-subagent | `route.py` | Excludes potentially best models for speed |

---

<details>
<summary>Cost reference (snapshot — verify before large runs)</summary>

The single source of truth for prices is the per-model `pricing` block in
`<SKILL_DIR>/models.json` (or `models.example.json`), which carries an `_as_of`
date. The chat parent should re-research any block where `_as_of` is older than
30 days OR where `endpoint.base_url` points to a proxy (proxy pricing diverges
10-100× from vendor list). The numbers below are illustrative only.

| Tier | Typical Input $/M | Typical Output $/M | Notes |
|------|-------------------|--------------------|-------|
| Discount proxies | ~$0.05–0.5 | ~$0.05–2.5 | Always re-research; rates shift weekly |
| Vendor list (BYOK) | ~$1–5 | ~$10–30 | See `pricing._as_of` per alias |
| Cursor-billed models | Billed to Cursor account | — | No per-token charge outside Cursor |

</details>
