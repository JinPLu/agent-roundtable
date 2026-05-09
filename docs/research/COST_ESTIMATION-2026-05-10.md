# Pre-flight Cost Estimation for `agent-roundtable` — Prior Art Survey

Date: 2026-05-10. Companion to `AGENT_LOOPS-2026-05-10.md`.
Scope: given `(actor, model, role, effort)`, can we estimate **before dispatch** the
tokens billed and the dollar amount? Surveys libraries, observability platforms,
academic work, and reasoning-token reality. Verifies recency of every claim.

## 1. TL;DR

There is **no drop-in library that takes `(provider, model, role-prompt,
project-snapshot) → (input_tokens, output_tokens, $-band)`**. The closest are
`tokencost` (AgentOps) and `genai-prices` (pydantic), but both are fundamentally
**post-hoc cost calculators**: they expect you to already know `(input, output)`
or to call a real tokenizer. Real client-side tokenization is impossible for
Claude 3+ and proprietary Cursor Composer, so the "predict tokens" half is
genuinely open.

**Recommendation: option (b) — keep our token-budget heuristic, but vendor the
pricing JSON from LiteLLM (`model_prices_and_context_window.json`).** The unit
prices are the part the world has solved; the per-role token-budget table is
the part nobody has solved well, and our `ROLE_TOKEN_BUDGETS × EFFORT × thinking`
heuristic is calibrated for our actual workload (5-part turns over a multi-file
project). That table should be re-tuned quarterly against `usage` payloads from
real dispatches.

## 2. Token-counting libraries

| Library | Scope | Model coverage as of latest release | Pricing data? | Source / version | Calibration recency |
|---|---|---|---|---|---|
| `tiktoken` (openai/tiktoken) | Real BPE (Rust core) | OpenAI only — `gpt-4o`, `o1`, `o3`, `gpt-5*`. **No Claude, no Gemini, no Cursor.** | No | github.com/openai/tiktoken `tiktoken/model.py` | Used as the "approximation" tokenizer by everyone else; works exactly for OpenAI families. |
| `@anthropic-ai/tokenizer` (TS) | Pre-Claude-3 BPE | Claude 1/2.1 only — vendor docs explicitly say "no longer accurate" for Claude 3+ | No | github.com/anthropics/anthropic-tokenizer-typescript | **Stale by design.** Anthropic recommends the server `count_tokens` endpoint instead. |
| Anthropic `POST /v1/messages/count_tokens` | Server-side, free, accurate | All current Claude models incl. extended thinking inputs | No (counts only) | docs.anthropic.com/en/api/messages-count-tokens | Authoritative for *input*; cannot predict output / thinking tokens. |
| `transformers` `AutoTokenizer` | Real BPE/SP for any HF-hosted model | Llama, Mistral, Qwen, DeepSeek, Phi, etc. — anything with public weights | No | huggingface.co/transformers | Right answer when the model has open weights; useless for closed APIs. |
| `tokencost` (AgentOps-AI) v0.1.26 | Cost calc. wraps `tiktoken` for OpenAI + `count_tokens` API for Anthropic | "400+ LLMs" (their pricing JSON pulls from LiteLLM-style sources) | Yes — bundled JSON | github.com/AgentOps-AI/tokencost; PyPI 0.1.26 | "Daily price updates" claim per release notes; Claude Opus 4.5 listed on the companion site `tokencost.app`, **Opus 4.7 not yet in offline JSON as of last release I could fetch**. |
| `genai-prices` (pydantic) v0.0.59 | Cost calc + usage extractor | 30+ providers, 583 OpenRouter models, Anthropic 18, OpenAI 68, Google 32 | Yes — versioned JSON | github.com/pydantic/genai-prices | Active; receives PRs per provider release (e.g., OpenRouter cost field PR #239). MIT. |
| HF TGI `/tokenize` | Real tokenizer over HTTP | Whatever the TGI deployment is serving | No | github.com/huggingface/text-generation-inference | Only useful if the executor is HF-hosted; not relevant to Cursor/Claude/GPT. |
| Google `genai` SDK `count_tokens` | Server-side | Gemini 2/3 incl. `thoughts_token_count` exposure | No | ai.google.dev/gemini-api/docs/tokens | Returns `usage_metadata.thoughts_token_count` post-hoc; pre-flight only counts inputs. |
| `llm` (Simon Willison) ≥ 0.19 | Logging + cost tags | Whatever plugin is installed | Yes (per-plugin) | simonwillison.net/2024/Dec/1/llm-019 | Stores `input_tokens` / `output_tokens` / `token_details` in SQLite — built for **post-hoc analysis**, not pre-flight. |

**Key empirical finding.** For every closed-API frontier model (Claude 3+,
GPT-5*, Gemini 3, Cursor Composer 2), client-side tokenization is at best a
4-chars-per-token heuristic. Anthropic explicitly tells you to use their server
endpoint or to read `usage` in the response. There is no offline alternative
that is "billing-grade."

## 3. Cost-aware platforms

| Platform | Pre-flight estimate? | Post-hoc accounting | Pricing registry | Token-count shim | Notes |
|---|---|---|---|---|---|
| LiteLLM (BerriAI) | Yes — `token_counter()` + `cost_per_token()` | Yes via `completion_cost()` | `model_prices_and_context_window.json` (~34k lines, MIT, updated by community PR; verified to contain `claude-opus-4-7`, `claude-opus-4-7-20260416`, `gpt-5.5`, `gemini-3.1-pro-preview`) | Uses `tiktoken` for OpenAI; falls back to model registry-declared char ratios for closed models | The single best pricing source. **No `cursor/` provider keys** as of the file fetched 2026-05-10 — if we want Cursor's pool pricing we still maintain it ourselves. |
| OpenRouter `/generation` + response `cost` field | Implicit (post-call) | Yes — every response carries `cost`, `cost_details.upstream_inference_cost`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cached_tokens`, `cache_write_tokens` | Live (their pricing page) | Native upstream tokenizer | The cleanest "what did this actually cost" surface. 5.5% platform fee on top of provider price. |
| Helicone | No pre-flight | Two paths: AI-Gateway (exact) vs "Best Effort" (model-detection + token-count heuristic, "300+ models"); FAQ: "How we calculate cost" | Open repo of pricing | tiktoken-style | Explicitly post-hoc. |
| Langfuse | No pre-flight (calls it "inferred" cost) | "Ingested" (from response) preferred; "inferred" used when missing | Yes | tokenizer per provider | Same shape as Helicone. |
| Portkey, LangSmith, Vercel AI SDK observability | No pre-flight (per docs scanned) | Yes | Bundled or fetched | Provider-native | All three are observability-first; estimation is a side effect of token logging. |
| Aider | Effectively post-hoc per turn | After every model reply: `"…tokens, $X cost, session cost: $Y"`; `/tokens` shows context-window cost only | Uses LiteLLM | LiteLLM's tokenizer | The user-facing UX template we should copy. |
| Continue / Cline | Not surfaced as pre-flight in docs scanned | Per-call usage shown | Inherits from chosen provider SDK | Provider SDK | No pre-dispatch budget UX. |
| **Cursor** dashboard / CLI | Per-request pool-burn after dispatch | "Auto + Composer pool" vs "API pool"; non-Auto agent requests add a flat **$0.25/M** Cursor Token Rate | Internal | Internal | No public pre-flight cost-estimate API. |
| **Promptmeter** (VS Code / Cursor extension) | **Yes — closest analog to ours.** Live status-bar token + cost as you type, clipboard auto-watcher, mode presets (Ask/Edit/Agent/Debug/Plan), pool-burn tracker, logs to `~/.cursor-preflight/usage.log` | Yes | Pulls from OpenRouter at startup; "300+ models" | Local approximation tokenizer | Closed-source (marketplace listing only; no public GitHub I could find). Confirms the **role/mode preset** approach we already use is the industry-standard pattern for Cursor pre-flight. |

## 4. Reasoning-token reality (verified from primary sources)

| Provider | API surface | Billing | Notes |
|---|---|---|---|
| OpenAI o-series, GPT-5* | `usage.completion_tokens_details.reasoning_tokens` | Billed as **output tokens** at the model's output rate. Hidden chain-of-thought, not returned in content. | Per `developers.openai.com/docs/guides/reasoning`, reasoning workloads "may generate anywhere from a few hundred to tens of thousands of reasoning tokens." `reasoning.effort` parameter takes `none | minimal | low | medium | high | xhigh`. |
| Anthropic Claude 4.x | `thinking` content blocks in the response; counts roll into `output_tokens` in `usage` | **Same rate as text output** (Sonnet 4 thinking and text both $15/M; Opus 4 both $25/M, per `awesomeagents.ai/pricing/reasoning-model-pricing/`). `budget_tokens` is documented as a *soft* ceiling. Manual `thinking.type:"enabled"` is removed on Opus 4.7 (returns 400) and deprecated on 4.6; adaptive thinking with `effort` is the new path. | Confirms our heuristic of treating thinking as an output multiplier rather than a separate axis. |
| Google Gemini 3 | `response.usage_metadata.thoughts_token_count` (separate field from `candidates_token_count`) | Per Vertex AI thinking docs, thinking tokens billed at the model's output rate. Gemini 3 Pro **cannot disable thinking**. `thinking_level` ∈ {`low`, `high`}. | First major provider to expose thinking tokens as their own field rather than rolling them into output. |

**Empirical reasoning-output ratio (primary-source observations).** Anthropic's
own SWE-Bench post for Claude 3.5 Sonnet (`anthropic.com/research/swe-bench-sonnet`)
runs at a 200k context with no thinking. The 2026-04 nilenso comparison
(`blog.nilenso.com/blog/2026/04/08/checking-my-model-vibes-against-swe-bench-pro/`,
616 paired tasks) reports a **median total-token ratio of 1.15× (Sonnet 4.5 vs
GPT-5)** and a **median cost ratio of 6.33×**, with Sonnet 4.5 outputting more
tool-call argument text (and that text being the thing SWE-agent's metrics
*undercount*). For Aider polyglot (225 tasks, leaderboard Yaml at
`github.com/Aider-AI/aider/blob/main/aider/website/_data/polyglot_leaderboard.yml`):
- GPT-5 (high): **$29.08** total → ~**$0.13 / task**
- GPT-5 (medium): **$17.69** → ~**$0.08 / task**
- Claude 3.7 Sonnet (32k thinking budget): **$36.83** → ~**$0.16 / task**
- o3-pro (high): **$146.32** → ~**$0.65 / task**
- o1-2024-12-17 (high): **$186.50** → ~**$0.83 / task**

These are single-shot polyglot edits; SWE-bench autonomous-agent turns are
1–2 orders of magnitude more expensive (the Princeton HAL leaderboard reports
**Claude Sonnet 4.5 High at $463.90** across SWE-bench Verified Mini, so order
$1–2 per task in the cheap regime, $5+ per task at high-effort autonomy).

## 5. Academic / public reports

- **FrugalGPT** — Chen, Zaharia, Zou; arXiv 2305.05176. Establishes that LLM
  unit prices span **two orders of magnitude** (GPT-4 at $30/10M tokens vs
  GPT-J at $0.20/10M tokens at the time) and that cost-aware *cascade*
  routing can match GPT-4 at up to 98% cost reduction. Does **not** publish
  a pre-flight token-prediction model — the cascade decides empirically by
  asking the cheap model first.
- **RouteLLM** — Ong et al., arXiv 2406.18665. Trains a router on human-pref
  data; reports >2× cost reduction at matched accuracy. Routing decision is
  per-query, not per-`(role,effort)`-bucket.
- **HF "How long is a piece of string?"** — Pearce et al., arXiv 2601.11518.
  Empirical analysis of tokenizers: confirms 1 token ≈ 4 English chars is
  "overly simplistic," that code lands closer to **3.0–4.2 chars/token** for
  cl100k (and lower for code-heavy BPE), and that JSON/code is significantly
  denser than prose.
- **SWE-bench mutation paper** — arXiv 2510.08996. Reports per-task token
  telemetry inside SWE-agent trajectories; flags that built-in metrics
  *undercount* tool-call argument tokens — directly relevant to our observation
  that Cursor's agentic input is much larger than chat input.
- **Anthropic Claude SWE-Bench engineering post** — `anthropic.com/research/swe-bench-sonnet`.
  Public methodology page; minimal scaffold, 200k context, no per-task token
  number published.

**No paper I could find publishes pre-flight cost-prediction RMSE/MAE for
autonomous coding agents.** The closest published numbers are the post-hoc
benchmark leaderboards above. This is a real gap.

## 6. Recommendation for `agent-roundtable`

**(b) Augment the heuristic by importing pricing data from LiteLLM; keep our
token-count heuristic.**

Concretely:
1. **Pricing source of truth = LiteLLM's `model_prices_and_context_window.json`.**
   Vendor a periodically refreshed snapshot (or fetch at install time). It is
   the only registry I verified to include `claude-opus-4-7`, `gpt-5.5`,
   `gemini-3.1-pro-preview` with prompt-cache and reasoning-aware fields. MIT.
   File to mirror in `scripts/lib/`: load JSON → dict keyed by canonical model
   id. Do **not** copy the whole file (1MB); whitelist the ~20 models we route
   to. Re-pull quarterly or after every model addition to `models.json`.
2. **Cursor Composer / pool pricing stays hand-maintained** — LiteLLM has no
   `cursor/` keys. Our `models.json` already encodes this; nothing to import.
   Add the **+$0.25/M Cursor Token Rate** to non-Auto agent rows (verified
   from `cursor.com/docs/account/teams/pricing`).
3. **Token-budget table stays heuristic.**
   - For *input*: there is no offline tokenizer that's correct for Claude or
     Cursor; tiktoken is the wrong answer for both. Use **chars/token = 3.5
     for code, 4.0 for prose, 2.8 for JSON** (HF arXiv 2601.11518). Multiply
     by `ROLE_TOKEN_BUDGETS[role]` to bound the project-snapshot bucket.
   - For *output*: keep `EFFORT_MULTIPLIERS`. For thinking-mode models, treat
     reasoning tokens as **output tokens at the same rate** (verified for
     OpenAI o-series, Anthropic 4.x, Gemini 3) and apply a `thinking_flag`
     ×3–10 multiplier on the executor / planner roles where chain-of-thought
     dominates.
4. **Quarterly recalibration.** Each dispatch already returns `usage` (or
   OpenRouter returns `cost` directly). Log `(actor, model, role, effort,
   prompt_tokens, completion_tokens, reasoning_tokens, $cost)` to
   `~/.roundtable/usage.log`; recompute `ROLE_TOKEN_BUDGETS` p50 / p95 from
   the last 30 days. This is the loop Promptmeter implements; we should mirror
   it.
5. **Don't depend on `tokencost` or `genai-prices`** at runtime. Both are
   thin wrappers over the same JSON LiteLLM publishes; adding them buys us a
   transitive dependency on `tiktoken` (correct only for OpenAI) and gives us
   nothing on the *prediction* axis we actually struggle with.

Migration cost: ~50 lines of `scripts/lib/` to load the pricing JSON snapshot
and a whitelist; the existing `estimate_cost.py` from the implementation
subagent owns the heuristic side. No SDK churn.

### 6.1.1 — 2026-05-10 update — implemented

- Vendored a 25-model whitelist of LiteLLM's pricing JSON to `scripts/lib/pricing_snapshot.json`. Cursor variants present as marker entries (`_no_litellm_source: true`) — the estimator continues to read their prices from `models.json`. Refresh manually via `python3 scripts/refresh_pricing_snapshot.py`.
- Added `scripts/lib/pricing_snapshot.py` loader (per-token → per-1M conversion documented at top). `estimate_cost.py` accepts `--source registry|snapshot|both`; `both` warns when registry vs. snapshot disagree by >10%.
- Added `scripts/lib/usage_log.py` and `scripts/lib/log_turn_usage.py`; `codex_turn.sh` and `claude_turn.sh` now append a JSONL record per turn to `$ROUNDTABLE_PROJECT_ROOT/.roundtable/usage.log` (schema in §6.4) without altering the wrapper exit status.
- Added `scripts/recalibrate_token_budgets.py`: prints proposed `ROLE_TOKEN_BUDGETS` / `EFFORT_MULTIPLIERS` based on observed p50; `--apply` rewrites the constants block in `estimate_cost.py` between `# BEGIN_AUTOGEN_*` / `# END_AUTOGEN_*` sentinels. Cells with <5 samples are refused.
- `ROLE_TOKEN_BUDGETS` numbers were intentionally NOT changed in this commit — the tooling shipped, the recalibration is a future operator action.

## 7. Open questions / gaps

1. **Cursor Composer 2 token-count truth.** Cursor exposes no
   `count_tokens`-style endpoint, and Composer is closed-source. Promptmeter
   uses an OpenRouter-based approximation; we should benchmark our heuristic
   against logged `usage` from real Cursor agent dispatches once we have ≥30
   logged turns.
2. **Adaptive-thinking cost variance.** Anthropic now uses `effort`-based
   adaptive thinking on Opus 4.7. There is no published distribution of
   reasoning tokens by effort level — we'd need to log dispatches across
   `low / medium / high / xhigh` and report p50 / p95 ourselves.
3. **Pre-flight RMSE/MAE for autonomous coding agents.** No academic source
   publishes this. Closing the gap requires our own log → recalibration loop
   (see §6.4). One blog-quality citation: SWE-Bench Pro paired runs (nilenso,
   2026-04) is the closest to "real-world distribution."
4. **`tokencost` / `genai-prices` exact Claude 4.7 / GPT-5.5 inclusion.**
   PyPI shows `tokencost==0.1.26` and `genai-prices==0.0.59` as latest at the
   time of writing; I verified the *companion website* `tokencost.app` lists
   Claude Opus 4.5 / 4.6 but did **not** read every entry of either library's
   bundled JSON. If we ever depend on them, we must check before each release
   that the latest model ids round-trip — easier to vendor LiteLLM directly.
5. **Cursor pricing-pool mechanics.** Cursor's "pool" abstraction (Auto +
   Composer pool vs API pool) is described in `cursor.com/docs/account/teams/pricing`
   but the exact rules for **how** non-Auto requests bill against the API
   pool with the +$0.25/M token rate aren't fully spelled out. Worth a
   verification ping after Cursor's next pricing update.

---

Primary sources consulted (all read or skimmed end-to-end on 2026-05-10):
- LiteLLM pricing JSON: `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`
- LiteLLM completion-cost docs: `docs.litellm.ai/docs/completion/token_usage`
- AgentOps tokencost: `github.com/AgentOps-AI/tokencost`, `pypi.org/project/tokencost/` (v0.1.26)
- pydantic genai-prices: `github.com/pydantic/genai-prices`, `pypi.org/project/genai-prices/` (v0.0.59)
- Anthropic count-tokens API: `docs.anthropic.com/en/api/messages-count-tokens`
- Anthropic extended-thinking + adaptive thinking: `docs.anthropic.com/en/build-with-claude/extended-thinking`, `platform.claude.com/docs/en/build-with-claude/adaptive-thinking`
- OpenAI reasoning guide: `developers.openai.com/docs/guides/reasoning`
- OpenAI o1: `developers.openai.com/docs/models/o1`
- Google Gemini thinking + tokens: `cloud.google.com/vertex-ai/generative-ai/docs/thinking`, `ai.google.dev/gemini-api/docs/tokens`
- OpenRouter usage accounting: `openrouter.ai/docs/guides/administration/usage-accounting`
- Helicone "how we calculate cost": `docs.helicone.ai/faq/how-we-calculate-cost`
- Langfuse cost tracking: `get.langfuse.com/docs/observability/features/token-and-cost-tracking`
- Aider session-cost issue: `github.com/Aider-AI/aider/issues/257`; polyglot leaderboard YAML
- Promptmeter marketplace: `marketplace.visualstudio.com/items?itemName=MrugankVora.promptmeter`
- Cursor Composer 2 + pricing: `cursor.com/docs/models/cursor-composer-2`, `cursor.com/docs/account/teams/pricing`
- FrugalGPT: arXiv 2305.05176; RouteLLM: arXiv 2406.18665
- Tokenizer empirical: arXiv 2601.11518 (`How Long Is a Piece of String?`)
- SWE-bench mutation: arXiv 2510.08996; nilenso paired-run 2026-04 blog post
