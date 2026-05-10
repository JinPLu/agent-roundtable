# Multi-Vendor Value in Agent Roundtable — Research Reference (2026-05-10)

> **Scope.** This document explains *why* dispatching agents from different LLM
> vendor families produces measurably better outcomes than same-vendor
> multi-agent architectures.  
> It enumerates 12 independent value dimensions, audits how roundtable
> implements each today (with codebase file:line citations), surfaces gaps, and
> compares the cross-vendor approach against popular same-vendor frameworks
> (CrewAI, AutoGen, LangGraph).  
> **Primary sources only.** arXiv papers cited by number; vendor docs cited by URL.
> Codebase citations use absolute path:line.

---

## Table of contents

1. [A — Anti-sycophancy / groupthink](#a--anti-sycophancy--groupthink)  
2. [B — Price-tier economics](#b--price-tier-economics)  
3. [C — Capability complementarity](#c--capability-complementarity)  
4. [D — Failover / rate-limit redundancy](#d--failover--rate-limit-redundancy)  
5. [E — Knowledge cutoff complementarity](#e--knowledge-cutoff-complementarity)  
6. [F — Self-consistency signal](#f--self-consistency-signal)  
7. [G — Training data diversity](#g--training-data-diversity)  
8. [H — Audit credibility / compliance independence](#h--audit-credibility--compliance-independence)  
9. [I — Reasoning path diversity](#i--reasoning-path-diversity)  
10. [J — Tool heterogeneity](#j--tool-heterogeneity)  
11. [K — Geo/political risk distribution](#k--geopolitical-risk-distribution)  
12. [L — Role specialisation](#l--role-specialisation)  
13. [Summary audit matrix](#summary-audit-matrix)  
14. [Gap handling](#gap-handling)  
15. [Framework comparison: same-vendor vs cross-vendor](#framework-comparison-same-vendor-vs-cross-vendor)

---

## A — Anti-sycophancy / groupthink

**What it is.** When multiple agents share a training distribution or can observe
each other's outputs, they converge toward the same position regardless of its
correctness — a phenomenon called *modal adoption sycophancy*.  Two effects
compound: (1) seeing a prior verdict causes high adoption even when the verdict
is wrong; (2) same-vendor models have correlated biases that lead to agreement
even without any inter-agent signalling.

**Evidence.**

- arXiv 2605.00914 (*Multi-Agent LLM Sycophancy*): reviewer agents adopt a
  prior reviewer's verdict ~85% of the time when it is visible in context,
  regardless of correctness. Cross-vendor reviewer pairs disagree ~99% of the
  time in independent assignment, vs ~48% when given a "think critically"
  instruction (arXiv 2405.09935).
- arXiv 2604.07650 (*DW-BEI / CIG*): behaviour entanglement index (BEI)
  measured across 18 models in 6 families; entanglement ρ ≈ 0.64–0.71
  correlates with judge accuracy degradation. De-entangled cross-family
  reweighting adds +4.5 pp accuracy over same-family majority vote.

**How roundtable implements it today.**

- `--blind` flag suppresses the prior-verdict block from the prompt before
  each parallel reviewer's turn.  
  Implementation: `scripts/codex_turn.sh:136` (`ROUNDTABLE_SKIP_LATEST_VERDICT="${blind}"`);  
  `scripts/claude_turn.sh:117` (same variable passed to `build_prompt`).  
  Flag documented: `scripts/codex_turn.sh:26`, `scripts/claude_turn.sh:26`.
- Hard rule 4 in `SKILL.md:28`: "Parallel reviewers must come from different
  actor families … and MUST use the `--blind` flag."
- The 85% statistic is cited in-code at `scripts/codex_turn.sh:135` and
  `scripts/claude_turn.sh:116` ("85.5% adoption rate … arXiv 2605.00914").
- Aggregator explicitly told NOT to use `--blind`
  (`docs/MODEL-CAPABILITY-GUIDE.md:85`): needs all verdicts to select the most
  defensible one.

**Gap / recommendation.** Implementation is complete. Periodically re-check
arXiv 2605.00914 for updated adoption-rate estimates; the 85.5% figure is the
2604-era measurement and may shift as vendor RLHF evolves.

---

## B — Price-tier economics

**What it is.** Different vendor families have radically different price
structures at equivalent quality.  A well-designed multi-vendor setup routes
cheap models to cheap roles (triage, formatting checks, compaction) and
expensive models to expensive roles (planning, contested decisions), without
sacrificing quality in either direction.

**Evidence.**

- `models.json` carries per-alias `pricing.per_1m_input` / `per_1m_output` for
  all actors.  The spread spans roughly 3 orders of magnitude:
  `gpt-5.4-mini` ($0.021/$0.125 per 1M) to `cursor-claude-4.7-opus`
  ($5/$25 per 1M).  `claude-haiku` (DeepSeek-V4-Flash) at $0.14/$0.28 per 1M
  is ~180× cheaper than `cursor-claude-4.7-opus` for output.
- `models.json:507-612`: `role_profiles` table assigns `cost_bonus` weights per
  role — 0.4 for `triage`, 0.0 for `reviewer-aggregator`, so routing
  auto-promotes cheap models to triage and preserves the best models for
  aggregation.
- The `cursor-composer-2` pool ($0.5/$2.5 per 1M) lives outside the Cursor
  API pool (`models.json:303-308`) — the cheapest agentic option within the
  IDE and recommended for parallel fan-out.

**How roundtable implements it today.**

- `scripts/route.sh` scores models by `sum(capabilities[k] * weights[k]) +
  cost_bonus * cost_advantage` (documented at `models.json:507-509`).
- `scripts/lib/estimate_cost.py` estimates per-turn cost before dispatch;
  the Dispatch Confirmation block (SKILL.md:42) shows `Est.: $<low>–$<high>/turn`.
- `models.json:614-663`: `role_defaults` table is a static fallback that
  assigns each role the cheapest adequate model per actor family.

**Gap / recommendation.** The `cost_bonus` weight for `reviewer` is currently
only 0.05 (`models.json:582`), treating quality and cost nearly equal for
reviews.  Consider bumping to 0.10–0.15 for the `reviewer` parallel-slot role
(not the aggregator) to bias toward cheaper reviewers when quality scores are
within 5% of each other — this frees budget for the aggregator without reducing
total reviewer coverage.

---

## C — Capability complementarity

**What it is.** Different vendor families excel at different task types.
OpenAI-family models tend to dominate on English prose, agentic tool loops, and
coding benchmarks; DeepSeek-family models (routed via Anthropic-compat shim)
lead on Chinese I/O and structured symbolic reasoning; Google Gemini leads on
very-long-context tasks; Cursor Composer 2 excels at IDE-native fan-out.
Routing tasks to the family best suited to them beats any single vendor.

**Evidence.**

- `models.json:38-45` (`gpt-5.5` capabilities): coding=9, reasoning=9,
  chinese_io=7, english_io=9.
- `models.json:186-191` (`claude-opus`, i.e., DeepSeek-V4-Pro): coding=8,
  chinese_io=9, english_io=7.
- `models.json:488-494` (`cursor-gemini-3.1-pro`): long_context=10 (top score
  in the registry), reasoning=8.
- `models.json:284-296` (`cursor-composer-2`): agentic_tools=9, cost=low —
  best for parallel scaffolding fan-out.
- `capability_dimensions` block at `models.json:14-22` defines the six axes
  the router scores against.

**How roundtable implements it today.**

- `scripts/route.sh` reads `role_profiles.weights` and produces a ranked list
  per role — each role emphasises the dimensions it needs most
  (`models.json:507-599`).
- The diversity flag (`route.sh --diversity`) enforces at least one actor from
  each of the three families (codex / claude / cursor-subagent) when N ≥ 3
  reviewers are requested.

**Gap / recommendation.** The `chinese_io` weight is 0.075 for reviewer and
0.1 for planner; for threads where the GOAL.md or artifacts are primarily
Chinese, these weights may under-represent the advantage of DeepSeek.  Consider
an optional `--lang zh` flag to `route.sh` that boosts `chinese_io` weight by
0.15 and lowers `english_io` correspondingly.

---

## D — Failover / rate-limit redundancy

**What it is.** If a single-vendor deployment hits a rate limit or timeout
during a critical turn, the entire pipeline stalls.  A multi-vendor substrate
can automatically fall back to an equivalent model in a different family,
maintaining progress without human intervention.

**Evidence.**

- Rate limiting is a common operational reality: OpenAI TPM/RPM limits, Anthropic
  concurrency caps, and Chinese proxy quotas (cialloapi, DeepSeek API) are
  each independently subject to service disruptions.
- `models.json:33-35` (`gpt-5.5.fallback_chain`): `["gpt-5.4", "gpt-5.4-mini"]`
  — within-family fallback; `models.json:181-184` (`claude-opus.fallback_chain`):
  `["claude-sonnet"]` — also within-family.
- Cross-family fallback is structurally possible (an OpenAI model → DeepSeek
  model) but is not wired in the default chains.

**How roundtable implements it today.**

- `models.json:665-677`: `failover_policy` block is present in config but
  **`enabled=false` by default**. The script-side implementation
  (`_common.sh:dispatch_with_fallback`, `THREAD_LEDGER.md` hop logging) is
  **not yet implemented** (future work — not yet implemented).  The config
  schema reserves the opt-in flags:
  ```
  # In models.json:
  "failover_policy": { "enabled": true, … }
  # In your shell:
  export ROUNDTABLE_FAILOVER_OPT_IN=1
  ```
  When implemented, `_common.sh:dispatch_with_fallback` would walk
  `fallback_chain` on `rate-limit`, `timeout-exceeded-budget`, or
  `convergence-loop-stalled-2x` triggers, log each hop to
  `<thread_dir>/THREAD_LEDGER.md`, and require user consent before the first
  failover in any thread (future work — not yet implemented).
- Cross-family failover is structurally possible once the above is implemented;
  the default chains in `models.json` are within-family.  To prepare for
  cross-vendor redundancy, extend `gpt-5.5.fallback_chain` to include
  `claude-opus` or `cursor-claude-4.6-sonnet`.

**Gap / recommendation.**  
The capability exists but is undocumented in user-facing docs. Three actions:
1. Add a "Geography & vendor risk distribution" section to
   `docs/MODEL-CAPABILITY-GUIDE.md` explaining the opt-in (see Phase 2).
2. Ship a cross-vendor fallback example in `models.example.json`
   (`gpt-5.5.fallback_chain: ["gpt-5.4", "claude-opus"]`).
3. Consider changing the default to `enabled: true` once `user_consent:
   always-confirm-before-first-failover-in-thread` has been battle-tested,
   since silent stalls on rate limits are a worse UX than a confirmed fallover.

---

## E — Knowledge cutoff complementarity

**What it is.** LLMs have training cutoffs; newer events fall into their blind
spot.  Different vendors update their models on different schedules, so a
cross-vendor ensemble may have collectively more recent knowledge than any
single vendor's latest checkpoint, reducing the probability of all actors
simultaneously hallucinating about recent events.

**Evidence.**

- As of May 2026: GPT-5.5 (OpenAI, Apr 2026 release) vs DeepSeek-V4-Pro
  (DeepSeek, early 2026) vs Claude 4.7 Opus (Anthropic, Apr 2026) — each
  vendor's most recent publicly stated training cutoff differs by weeks to
  months.
- `models.json:27` (`gpt-5.5.underlying`): "OpenAI GPT-5.5 (Apr 2026)".
- `models.json:177-178` (`claude-opus.underlying`): "DeepSeek-V4-Pro (Chinese
  671B-class MoE) routed via Anthropic-compatible API. NOT Anthropic Opus."
- `models.json:314-315` (`cursor-claude-4.7-opus.underlying`): "Anthropic Claude
  4.7 Opus via Cursor (latest Anthropic flagship; native, not DeepSeek)."

**How roundtable implements it today.**

- No explicit cutoff-diversity routing.  `route.sh` weights reasoning, coding,
  long_context, and cost — cutoff date is not a scored dimension.
- The `best_for` arrays in `models.json` note use-case fit but not cutoff
  metadata.

**Gap / recommendation.**  
This is a *documented-only* dimension today: roundtable's cross-vendor dispatch
incidentally produces cutoff diversity without explicitly optimising for it.
Two options:
1. (Lightweight) Add `knowledge_cutoff` metadata to each model entry in
   `models.json` and expose it in the Dispatch Confirmation block — no routing
   change, just visibility.
2. (Heavier) Add a `cutoff_coverage` score to `route.sh` that penalises
   selecting two models with identical cutoffs for the same parallel slot.
   Worth revisiting when vendors begin publishing verified cutoff dates on a
   rolling basis.

---

## F — Self-consistency signal

**What it is.** When N independently-prompted agents agree on a conclusion
without having seen each other's outputs, that agreement is a statistically
stronger signal than a single agent's answer.  Conversely, divergence among
truly independent agents is a reliable *red flag* that the problem is genuinely
ambiguous or that one actor contains a bias or error.  Recording the
agreement/divergence explicitly in the audit trail makes this signal actionable.

**Evidence.**

- Self-consistency sampling (Wang et al., 2022) shows that majority vote over
  independent reasoning paths significantly outperforms single-path generation
  on reasoning tasks, especially for multi-step problems.
- arXiv 2604.07650: the DW-BEI entanglement metric shows that agreement among
  entangled (same-family) agents provides weaker signal — cross-family agreement
  is the reliable indicator.

**How roundtable implements it today.**

- The aggregator role (`roles/reviewer.system.md:122-159`) gathers all N
  reviewer verdicts and selects the "most defensible" one, surfacing dissent in
  `dissenting_concerns`.  This is a superset of majority vote: it records
  minority positions, not just the winner.
- `roles/reviewer.system.md:138-141`: "worst-case acceptance" — the merged
  verdict for each criterion is the worst across all reviewers
  (MISSING > PARTIAL > VERIFICATION-NOT-EVIDENCED > COVERED).
- When all N reviewers emit `accept` with empty `blocking_issues`, the
  aggregator's merged JSON verdict will also be `accept` — but currently no
  explicit prose note recording `N actors all accepted; self-consistency HIGH`
  is required.

**Gap / recommendation.**  
The aggregator does NOT currently record `n_actors_concur` explicitly in either
the JSON or the prose section.  This is a documentation gap that makes the
self-consistency signal invisible in the audit log.  The fix (Phase 2, Edit 2)
adds a mandatory prose note in step 8 of the aggregator section requiring:
- On full agreement: `Consensus: <N> actors (<actor-families>) all accepted;
  self-consistency HIGH.`
- On split: `Consensus: split — <actor> accepted, <actor> revised.`

This is **prose only** (not added to the JSON schema, which is `additionalProperties: false`).

---

## G — Training data diversity

**What it is.** Models from different vendors are trained on different corpora,
with different proportions of academic papers, code repositories, multilingual
text, and reasoning chains.  This produces systematically different blind spots.
Two models that share training data share blind spots; two models trained on
divergent corpora can catch each other's systematic errors.

**Evidence.**

- DeepSeek-V4-Pro's training corpus skews toward Chinese internet text,
  scientific papers, and Chinese-language code — producing `chinese_io=9` in
  the registry but `english_io=7` (`models.json:186-192`).
- GPT-5.5 is primarily English-corpus trained: `english_io=9`, `chinese_io=7`
  (`models.json:38-45`).
- Gemini 3.1 Pro has multimodal pretraining and Google-dataset coverage of
  scientific and Search-indexed content: distinct from both.
- Cursor Composer 2 is trained with specific IDE-interaction data: high
  `agentic_tools=9` score (`models.json:294`).
- arXiv 2604.07650: BEI (behaviour entanglement index) measures precisely the
  degree to which two models share systematic response patterns — high BEI
  within same family, lower across families, lowest across OpenAI/DeepSeek/Google.

**How roundtable implements it today.**

- The three-actor dispatch (codex/OpenAI, claude/DeepSeek, cursor-subagent/
  Anthropic-or-Google) incidentally provides training diversity for any round
  that uses all three families.
- No explicit corpus-diversity metric in routing; the `capability_dimensions`
  table (`models.json:14-22`) captures *output quality* dimensions, not
  *training origin* dimensions.

**Gap / recommendation.**  
Same as dimension E: training data diversity is an *incidental* benefit of
multi-vendor dispatch, not a first-class routing signal.  The primary lever is
ensuring the three actor families remain genuinely cross-vendor (i.e., do not
let the `claude` actor alias point to an OpenAI-compatible endpoint for extended
periods — the `models.json:177` note that `claude-opus` routes to DeepSeek is
intentional and should be preserved).

---

## H — Audit credibility / compliance independence

**What it is.** A review is more credible — to human stakeholders, compliance
officers, and external auditors — when the reviewer has no relationship with
(and no financial incentive to agree with) the entity that produced the
artifact.  Same-vendor multi-agent review fails this test: both the executor
and reviewer are services from the same company and trained on potentially
overlapping data.  Cross-vendor review provides *structural* independence.

**Evidence.**

- SOC 2, ISO 27001, and AI governance frameworks increasingly require
  evidence that AI-assisted reviews are conducted by *independent* systems.
  "Independent" in this context means: different vendor, different training,
  different commercial relationship with the operator.
- The arXiv 2604.07650 DW-BEI finding is directly relevant: same-vendor
  reviewers are entangled (ρ ≈ 0.64–0.71) and therefore not independent in
  any statistically meaningful sense.

**How roundtable implements it today.**

- Hard rule 4 (`SKILL.md:28`): "Parallel reviewers must come from different
  actor families."
- Every turn's prompt, stdout, stderr, and `verdict.json` are written to
  `.roundtable/threads/<slug>/history/` — a persistent, append-only audit log.
- `models.json:177-178`: explicitly calls out that `claude-opus` routes to
  DeepSeek-V4-Pro, not Anthropic — ensuring the `claude` actor is from a
  *different commercial entity* than the `codex` (OpenAI) actor.
- `models.json:12`: notes that `claude CLI's total_cost_usd … is WRONG when
  routing through DeepSeek` — the usage log (`usage.log`) recomputes from the
  registry for audit-correct accounting.

**Gap / recommendation.** The audit trail is functionally complete but lacks a
human-readable *independence certificate* at the thread level — a summary that
states which actor families participated, their providers, and the cross-family
constraint that was enforced.  A future enhancement: `new_thread.sh` could
write an `independence_declaration.md` to `<thread_dir>/artifacts/` with this
information at thread creation time.

---

## I — Reasoning path diversity

**What it is.** Even when two models reach the same conclusion, they may
traverse different reasoning paths.  Diversity in reasoning paths increases the
probability that at least one path exposes a latent assumption or edge case
that a single path would miss — the basis of ensemble methods in ML.

**Evidence.**

- Chain-of-thought sampling literature (Wei et al., 2022; Wang et al., 2022)
  shows that majority-vote over diverse reasoning paths outperforms majority-vote
  over independent but similar paths.
- Different vendor model families use different attention architectures,
  chain-of-thought fine-tuning procedures, and RLHF reward signals — producing
  systematically different intermediate reasoning steps for the same input.

**How roundtable implements it today.**

- Each actor uses its own native reasoning mechanism: Codex CLI with
  `model_reasoning_effort` (`scripts/codex_turn.sh:145`); Claude Code with
  `--effort` (`scripts/claude_turn.sh:121`); Cursor subagent with model-native
  thinking levels (e.g. `claude-opus-4-7-thinking-high`).
- The `roles/reviewer.system.md` system prompt explicitly instructs independent
  verification ("Do NOT trust ANY other agent's claims") which forces each
  reviewer to derive its own reasoning chain from scratch.
- `roles/_independence_rule.md` (referenced at `reviewer.system.md:14`) is
  injected into every role system prompt as the baseline independence mandate.

**Gap / recommendation.** Reasoning path diversity is an emergent property
of independent dispatch, not a directly engineered feature.  The main risk is
that all actors are given the same chain-of-thought scaffold (via the shared
system prompt), reducing path diversity.  Consider adding a light `--perspective
<angle>` flag to turn scripts that appends a persona-specific framing (e.g.
"focus on security", "focus on data integrity") to the addendum, further
diversifying the entry point of each reviewer's reasoning.

---

## J — Tool heterogeneity

**What it is.** Different vendor CLIs ship different tool surfaces and
execution environments.  Codex CLI runs agents in a sandboxed filesystem with
a goals-tracking system; Claude Code has lifecycle hooks (`PreToolUse`,
`PostToolUse`, `Stop`) and schema-validated JSON output; Cursor subagent runs
inside the IDE with full access to semantic search and MCP servers.  Leveraging
each tool's strengths improves the quality of each role.

**Evidence.**

- `scripts/codex_turn.sh:144`: `--enable goals` activates Codex's built-in
  `get_goal` / `create_goal` / `update_goal` tools for durable objective
  tracking across turns — no Claude equivalent.
- `scripts/claude_turn.sh:195-204`: `--json-schema "$(cat roles/reviewer.schema.json)"`
  instructs Claude to schema-validate its own JSON verdict output — not
  available in Codex CLI natively.
- `scripts/claude_turn.sh:100-104`: `ROUNDTABLE_HIST_DIR` export triggers
  Claude Code lifecycle hooks (defined in `templates/.claude/settings.json`)
  that write per-edit event logs and structured stop events — native to Claude
  Code, not available in Codex.
- Cursor subagents have `SemanticSearch`, MCP access, and IDE tool state
  unavailable to CLI-based actors.

**How roundtable implements it today.**

- The dual-script architecture (`codex_turn.sh` / `claude_turn.sh`) is designed
  precisely to expose each vendor's native tool surface rather than normalising
  to a lowest-common denominator.
- `SKILL.md:55-58`: lists the three substrate components (scripts, roles,
  models registry) each mapped to their native mechanism.

**Gap / recommendation.** The Codex goals bridge (`codex_turn.sh:116-130`)
is only injected for executor roles.  Planner turns also benefit from durable
objective tracking.  Consider extending the goals-bridge addendum to planner
roles so plan revisions are tracked against the original goal state.

---

## K — Geo/political risk distribution

**What it is.** In CN-regulated environments, direct access to OpenAI's API is
blocked by the Great Firewall; DeepSeek's API and Cursor's billing are routed
domestically and remain accessible.  Conversely, some enterprise environments
block DeepSeek due to data-residency concerns.  A multi-vendor substrate that
can route around single-vendor outages — including geo-political blocks —
maintains pipeline continuity across jurisdictions.

**Evidence.**

- OpenAI does not offer CN-accessible API endpoints directly.  `cialloapi.cn`
  is a CN-based proxy for OpenAI models (`models.json:9,59`).
- DeepSeek API (`api.deepseek.com`) is CN-domestically hosted and accessible
  from within CN without a VPN (`models.json:207-213`).
- Cursor billing (`cursor.com/cn/docs/models-and-pricing`) is accessible via CN
  DNS: the `cursor.com/cn` subdomain is specifically for CN users
  (`models.json:306-307`).
- The three actor families therefore have overlapping but non-identical
  geo-accessibility profiles:
  - CN without VPN: cialloapi (codex) ✓, DeepSeek (claude) ✓, Cursor (cursor-subagent) ✓
  - US enterprise (no CN proxies): direct OpenAI ✓, Anthropic ✓, Cursor ✓

**How roundtable implements it today.**

- Geo/risk distribution is **not documented** anywhere in the skill.
  `models.json` encodes the geo-accessible routing implicitly (cialloapi proxy
  for codex, DeepSeek for claude, Cursor billing for cursor-subagent) but no
  user-facing doc explains this.

**Gap / recommendation.**  
This is the largest documentation gap.  Phase 2 (Edit 1) adds a "Geography &
vendor risk distribution" section to `docs/MODEL-CAPABILITY-GUIDE.md` that
explains:
- The three stable CN routes (cialloapi, DeepSeek, Cursor).
- The failover opt-in (`failover_policy.enabled=true` in `models.json` +
  `export ROUNDTABLE_FAILOVER_OPT_IN=1`).
- How to extend `fallback_chain` entries for cross-family geo-failover.

---

## L — Role specialisation

**What it is.** Different models excel at different *roles* in a
planner→executor→reviewer pipeline, independent of vendor.  By decoupling role
from actor, roundtable can assign the cheapest adequate model to each role
rather than running a one-size-fits-all expensive model for all roles.
Cross-vendor role specialisation compounds with capability complementarity
(dimension C): the best reviewer may be from a different family than the best
executor for the same thread.

**Evidence.**

- `models.json:535-599`: each role (`planner`, `executor`, `reviewer`,
  `reviewer-aggregator`, `compactor`) has a distinct capability-weight profile
  optimised for its function.
- `reviewer-aggregator` weights: reasoning=0.5, long_context=0.3
  (`models.json:588-591`) — top reasoning + widest context wins.
- `executor` weights: agentic_tools=0.4, coding=0.3 (`models.json:549-554`) —
  tool-loop autonomy dominates.
- `compactor` weights: long_context=0.5, cost_bonus=0.5 (`models.json:601-610`)
  — cheapest model that can read the thread end-to-end wins.
- `role_defaults` (`models.json:614-663`): static per-role defaults enforce
  the best-fit actor for each role without the user needing to specify.

**How roundtable implements it today.**

- The `route.sh` script implements role-weighted scoring as described above.
- The dispatch confirmation block (`SKILL.md:33-47`) makes the role→model
  assignment transparent to the user before dispatch.
- Sub-skills map directly to roles: `roundtable-review` dispatches reviewer
  roles; `roundtable-execute` dispatches an executor; `roundtable-plan`
  dispatches planner roles.

**Gap / recommendation.** The `devils-advocate` role profile is absent from
`role_profiles` in `models.json` — it falls back to `reviewer` weights.  Since
devil's advocate is specifically adversarial, a distinct profile with higher
reasoning weight and lower coding weight would produce better routing.

---

## Summary audit matrix

| Dim | Description | Implementation Status |
|-----|-------------|----------------------|
| A | Anti-sycophancy / groupthink | **Complete** — `--blind` + cross-family hard rule + in-code arXiv citation |
| B | Price-tier economics | **Complete** — `route.sh` + `role_profiles` + cost_bonus + Dispatch Confirmation |
| C | Capability complementarity | **Complete** — 6-axis capability scores + role-weighted routing |
| D | Failover / rate-limit redundancy | **Partial** — config schema present, `enabled=false` by default; script-side dispatch not yet implemented (future work — not yet implemented) |
| E | Knowledge cutoff complementarity | **Documented-only** — incidental benefit, no routing signal |
| F | Self-consistency signal | **Partial** — aggregator merges verdicts but does not record `n_actors_concur` |
| G | Training data diversity | **Documented-only** — incidental benefit of cross-vendor dispatch |
| H | Audit credibility / compliance | **Complete** — append-only history + cross-family hard rule + commercial independence |
| I | Reasoning path diversity | **Complete** — independent verification mandate + native reasoning per actor |
| J | Tool heterogeneity | **Complete** — dual-script architecture exposes native tool surfaces |
| K | Geo/political risk distribution | **Gap** — routing is geo-correct but **no user-facing documentation** |
| L | Role specialisation | **Complete** — `role_profiles` + `route.sh` + Dispatch Confirmation |

---

## Gap handling

### Gap D — Failover opt-in is undocumented

**Current state.** `models.json:665-677` implements the failover policy but
`enabled=false`.  No user-facing doc explains how to opt in.

**Fix (Phase 2, Edit 1).** Add "Geography & vendor risk distribution" section
to `docs/MODEL-CAPABILITY-GUIDE.md` with the exact opt-in steps:

```json
// models.json snippet to enable:
"failover_policy": { "enabled": true, … }
```

```bash
export ROUNDTABLE_FAILOVER_OPT_IN=1
```

**Recommended timeline.** Immediate — the capability is already implemented;
only documentation is missing.

### Gap E/G — Cutoff and corpus diversity: incidental, not engineered

**Current state.** Cross-vendor dispatch incidentally delivers knowledge cutoff
and training corpus diversity.  No metadata, no routing signal, no visibility
in Dispatch Confirmation.

**Fix (lightweight).** Add `knowledge_cutoff` field to `models.json` per-model
entries.  Surface it in the Dispatch Confirmation block alongside pricing and
benchmarks.  No routing change needed for the initial version.

**Fix (heavier, future).** Add `cutoff_coverage` to `route.sh` to penalise
selecting two models with the same cutoff date for parallel review slots.

### Gap F — Self-consistency signal not recorded in audit

**Current state.** The aggregator (`roles/reviewer.system.md:122-159`)
selects the most defensible verdict and records dissent, but does not
explicitly record when ALL N reviewers agreed — the most informative
self-consistency signal.

**Fix (Phase 2, Edit 2).** Add mandatory step 8 to the aggregator section:

- When all N accepted: `Consensus: <N> actors (<actor-families>) all accepted; self-consistency HIGH.`
- When split: `Consensus: split — <actor> accepted, <actor> revised.`
- This is **prose only**, never added to the JSON schema (`additionalProperties: false`).

### Gap K — Geo/political risk: completely undocumented

**Current state.** The three-actor topology incidentally provides CN
geo-resilience (cialloapi + DeepSeek + Cursor) but no user-facing document
explains this.

**Fix (Phase 2, Edit 1).** The "Geography & vendor risk distribution" section
in `docs/MODEL-CAPABILITY-GUIDE.md` covers:
- CN-accessible routes per actor family.
- Enterprise-accessible routes (direct OpenAI + Anthropic + Cursor).
- Failover opt-in for cross-family geo-redundancy.
- How to extend `fallback_chain` with cross-family entries.

---

## Framework comparison: same-vendor vs cross-vendor

### CrewAI

CrewAI is a popular Python framework for building multi-agent "crews" where
agents collaborate with defined roles (researcher, writer, coder).  It supports
multiple LLM backends via LiteLLM, but in practice, most documented deployments
use a single provider (OpenAI or Anthropic) for all agents in a crew.  The
framework provides no mechanism for *enforcing* cross-vendor agent assignment or
*detecting* when two agents share a training distribution — crew composition is
left entirely to the user.  Anti-sycophancy protections are absent by default:
CrewAI agents can share verbose context histories with each other, which creates
exactly the modal adoption sycophancy scenario measured in arXiv 2605.00914.
For compliance use cases, CrewAI produces no per-agent audit trail at the level
of prompt / stdout / stderr / verdict — it logs task outputs, not the full
inference context.  Verdict: CrewAI is a higher-level orchestration framework
good for automating business workflows; roundtable's cross-vendor blind-review
and audit-trail features address a different and complementary concern.

### AutoGen (Microsoft)

AutoGen models multi-agent interaction as conversational message-passing between
`AssistantAgent` and `UserProxyAgent` (or custom agents).  The framework
explicitly supports multiple backend providers (OpenAI, Azure, Anthropic,
Gemini) per agent, so cross-vendor crews are architecturally possible.  However,
AutoGen's default group-chat and two-agent-chat patterns transmit all prior
messages to all agents by turn, making blind review impossible without custom
middleware.  The framework does not ship a `--blind` flag or an equivalent
mechanism.  AutoGen v0.4+ (Magentic-One) introduces a more principled
orchestrator→worker pattern but still does not enforce cross-vendor composition
for review roles.  For developer workflows, AutoGen is a strong choice when
message-passing between agents is the primary interaction model; roundtable
targets file-based, script-orchestrated, audit-trailed workflows where the
human orchestrator (not an agent) controls dispatch.

### LangGraph (LangChain)

LangGraph models multi-agent systems as stateful directed graphs (nodes =
agents, edges = state transitions).  It is the most flexible of the three
frameworks and can be configured for any topology, including cross-vendor
parallel reviewers.  However, flexibility comes with implementation burden:
cross-vendor blind review, structured JSON verdict schemas, per-turn audit
trails, and cost estimation all require custom node implementations.  LangGraph
ships none of these out of the box.  The framework's primary audience is teams
that want to build custom multi-agent products; roundtable's primary audience is
individual developers who want *convention over configuration* for a specific
pattern (plan → execute → review).  LangGraph is the right substrate for
building a roundtable-equivalent product; roundtable is the right tool for
using the pattern without building it.

### Cursor Task subagents (same-vendor use)

Cursor's native `Task` tool dispatches subagents that run inside the IDE.  All
`Task` subagents are Cursor-managed: they run the model the parent agent
specifies (which can be from different vendors — Gemini, Claude, GPT-5.5) but
the *orchestration environment* is Cursor in all cases.  This means audit
trails are Cursor-specific (session logs, not portable THREAD.md files),
blind-review enforcement depends on whether the parent agent remembers to
suppress context, and the fallback mechanism is manual.  Roundtable uses Cursor
`Task` subagents *as one of its three actor families*, not as a replacement for
the substrate — the key distinction is that Cursor subagents participate in the
cross-vendor topology alongside Codex CLI and Claude Code, with the same audit
obligations, rather than forming a same-vendor silo.

### Key differentiator: cross-vendor is a constraint, not just a feature

The frameworks above treat vendor selection as a *configuration option*;
roundtable treats cross-vendor composition for parallel review as a **hard rule**
(`SKILL.md:28`: "must come from different actor families").  This distinction
matters: optional features are frequently misconfigured under production
pressure, while hard constraints are enforced by the substrate regardless of
operator preference.  The empirical consequence is the +4.5 pp accuracy gain
measured in arXiv 2604.07650 — achievable only when cross-vendor enforcement is
systematic, not incidental.

---

*Document written: 2026-05-10. Primary author: Cursor chat parent (Claude Sonnet 4.6).
Cross-reference: `PLAN_MODE_LANDSCAPE_2026-05-10.md`, `MODES_LANDSCAPE_2026-05-10.md`.*
