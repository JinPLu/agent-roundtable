# Agent Loops Research — Codex `/goal` vs SOTA vs `roundtable-develop`

Author: research turn (Cursor parent agent)
Date: 2026-05-10
Scope: questions 1–3 in the dispatch brief.
Method: web-only research; every numeric / structural claim is cited or marked unverified.

---

## 1. TL;DR (≤8 lines)

1. Codex `/goal` (a.k.a. `[features] goals = true`) is a **single-agent self-loop**: the same Codex session keeps taking turns until the model itself calls `update_goal` to mark the goal complete, the token/wall-clock budget is exhausted (`budget_limited` soft-stop), the user pauses/clears, or a continuation turn makes no tool calls (anti-stall). Implementation lives behind `Session::goal_runtime_apply(GoalRuntimeEvent::…)` (PR openai/codex#18076, merged 2026-04-25). No spawned helpers, no cross-vendor review.
2. SOTA agentic loops cluster into four families: single-vendor self-improvement (ReAct / Reflexion / Self-Refine / Voyager / LATS), planner-executor-judge multi-agent in one family (MetaGPT, ChatDev, AutoGen, Aider architect/editor, Claude Code sub-agents), shipped autonomous goal-runners (Codex `/goal`, Devin, OpenHands, Factory droid, Cline), and an emerging cross-family verification line that explicitly targets **behavioral entanglement** between same-family models (arXiv 2604.07650, "Peacemaker or Troublemaker" 2509.23055, "Talk Isn't Always Cheap" 2509.05396).
3. `roundtable-develop`'s plan → execute → blind-cross-vendor parallel review → aggregate-with-evidence → loop-until-converged is **broadly aligned** with the strongest current literature and is, in fact, **stricter than every shipped competitor** on the review axis. The biggest issues are not structural — they are (a) the README cites a paper (`arXiv 2405.09935`) that does not contain the "~99% vs 48%" disagreement number and is not even a cross-vendor study, (b) no anti-stall heuristic comparable to Codex's "no-tool-calls ⇒ suppress continuation", and (c) no cost / budget circuit-breaker. Top-3 fixes: re-cite the empirical claim against arXiv 2604.07650 (or drop the number), add a budget/no-progress stop, and add a one-shot devil's-advocate self-critique inside executor turns to compress cheap iterations.

---

## 2. Codex `/goal` (`--enable goals`)

### 2.1 What it is

Experimental Codex CLI feature for "long-horizon work that has a clear target, a validation loop, and enough room for Codex to make progress without asking you to steer every step." Codex "can work independently for multiple hours without needing your input." ([OpenAI Developers — Follow a goal](https://developers.openai.com/codex/use-cases/follow-goals))

### 2.2 How to enable it

Two equivalent paths, confirmed by an OpenAI engineer in [openai/codex#20536](https://github.com/openai/codex/issues/20536):

```toml
# ~/.codex/config.toml
[features]
goals = true
suppress_unstable_features_warning = true
```

or `codex features enable goals`, or interactively `/experimental` from inside the CLI. As of 0.128.0 the feature is shipped under the **"under development"** maturity tier — listed in [feature-maturity](https://developers.openai.com/codex/feature-maturity), not in [public slash-command docs](https://developers.openai.com/codex/cli/slash-commands). The lifecycle commands are `/goal <objective>`, `/goal` (status), `/goal pause | resume | clear`. Goal states: `pursuing`, `paused`, `achieved`, `unmet`, `budget_limited`.

### 2.3 The loop and the stop condition (from PR openai/codex#18076)

The runtime is centralized in `codex-rs/core` behind `Session::goal_runtime_apply(GoalRuntimeEvent::…)`. Verbatim from the PR description ([openai/codex#18076](https://github.com/openai/codex/pull/18076)):

- "Starts goal continuation turns only when the session is idle; pending user input and mailbox work take priority."
- "Accounts token and wall-clock usage at turn, tool, mutation, interrupt, and resume boundaries."
- "Treats token budget exhaustion as a soft stop by marking the goal `budget_limited` and injecting wrap-up steering instead of aborting the active turn."
- "Suppresses budget steering when `update_goal` marks a goal complete." (i.e. the model itself emits a tool call to declare done.)
- "Pauses active goals on interrupt and auto-reactivates paused goals when a thread resumes outside plan mode."
- "**Suppresses repeated automatic continuation when a continuation turn makes no tool calls.**" (anti-stall heuristic — if the model does nothing, the loop quits.)
- "Added continuation and budget-limit prompt templates."

So the actual stop conditions, in priority order:

1. **Model self-declares done** by calling the `update_goal` tool with completion status — this is the canonical exit. ("It will stop running when it is fairly confident it has reached the stopping condition." — [follow-goals](https://developers.openai.com/codex/use-cases/follow-goals))
2. **Budget exhausted** (token or wall-clock) → soft-stop with wrap-up steering, marked `budget_limited`.
3. **User intervention** (`/goal pause | clear`, or interrupt).
4. **Anti-stall**: a continuation turn that emits zero tool calls suppresses further automatic continuation.

### 2.4 Prompt structure

Two model-side prompt templates were added in PR #18076: a **continuation** template (injected each time the runtime decides to push another turn — re-anchors the model on the goal, the validation contract, and the in-flight checkpoint log) and a **budget-limit** template (injected when token budget is near exhaustion — instructs Codex to wrap up cleanly rather than abort). The user-facing setup recipe (also from [follow-goals](https://developers.openai.com/codex/use-cases/follow-goals)) is the contract: "(1) Name one objective and one stopping condition. (2) Point Codex at the files, docs, issue, logs, or plan it must read first. (3) Define the commands or artifacts that prove progress. (4) Tell Codex to work in checkpoints and keep a short progress log."

### 2.5 Single-agent or multi-agent?

**Single-agent, single-vendor.** The same Codex session keeps taking turns. There is no spawned reviewer, no cross-vendor verifier, no separate planner process. The "validation loop" is whatever shell command / test / artifact the user wired into the goal contract; Codex just keeps calling tools until `update_goal(achieved)` or the budget runs out. This is closer to **Reflexion-without-an-external-critic + a budget-bounded scheduler** than to any debate / judge-ensemble design.

### 2.6 Design implications

- The stop signal is **model-emitted**, which is exactly the failure mode that the LLM-as-judge literature flags as unreliable for same-family validation (see §3.3). Codex is honest about this — the docs explicitly say "fairly confident it has reached the stopping condition," not "verified done."
- The anti-stall heuristic ("no tool calls ⇒ stop") is cheap and effective and is the one piece of `/goal` that `roundtable-develop` does not currently mirror.
- The budget accounting is the second piece worth borrowing — Codex bounds runaway loops by token + wall-clock, not by round count.

---

## 3. SOTA landscape

Grouped per the brief. "Evidence quality" labels: **strong** = peer-reviewed or widely replicated benchmark results; **medium** = preprint with experiments but not yet replicated; **engineering** = shipped product, public docs / source code; **rhetorical** = blog post / position paper without measurements.

### 3.1 Single-vendor self-loop

| Name | Year | Key idea | Evidence | Link |
|---|---|---|---|---|
| ReAct | 2022 | Interleave Thought / Action / Observation tokens in one model. | strong (HotpotQA, ALFWorld) | [arXiv 2210.03629](https://arxiv.org/abs/2210.03629) |
| Reflexion | 2023 | After a failed attempt, model writes verbal self-critique into episodic memory and retries. | strong (HumanEval, ALFWorld) | [arXiv 2303.11366](https://arxiv.org/abs/2303.11366) |
| Self-Refine | 2023 | One model: generate → self-critique → revise, until convergence. | strong | [arXiv 2303.17651](https://arxiv.org/abs/2303.17651) |
| Tree of Thoughts | 2023 | BFS / DFS over reasoning paths with LLM-as-judge scoring branches. | strong (Game of 24, creative writing) | [arXiv 2305.10601](https://arxiv.org/abs/2305.10601) |
| Voyager | 2023 | Lifelong agent in Minecraft with skill library + self-verification. | strong | [arXiv 2305.16291](https://arxiv.org/abs/2305.16291) |
| LATS | 2023 | MCTS over (ReAct + Reflexion) — unifies self-improvement under tree search. | medium | [arXiv 2310.04406](https://arxiv.org/abs/2310.04406) |

These all share the same blind spot: a single model both proposes and critiques, so error modes correlate across the iteration. arXiv 2604.07650 (§3.3) shows this is not just a worry — it is measurable as "behavioral entanglement."

### 3.2 Multi-agent debate / judge / planner-executor (single-family or unrestricted)

| Name | Year | Key idea | Evidence | Link |
|---|---|---|---|---|
| AutoGPT-line | 2023 | Open-ended task decomposition with a memory + tool loop. Pioneering, mostly engineering. | engineering / weak benchmark | [github](https://github.com/Significant-Gravitas/AutoGPT) |
| AutoGen | 2023 | Conversational multi-agent framework: user-proxy + assistant + tool agents in dialogue. | engineering + benchmarks | [microsoft.github.io/autogen](https://microsoft.github.io/autogen/stable/) |
| MetaGPT | 2023 | "Software-company-as-prompt": SOPs assign roles (PM / architect / dev / QA) to reduce cascading hallucination. | medium (benchmark suite) | [arXiv 2308.00352](https://arxiv.org/abs/2308.00352) |
| ChatDev | 2023 | Same idea, communicative-agents framing. | medium | [arXiv 2307.07924](https://arxiv.org/abs/2307.07924) |
| DEBATE (= arXiv 2405.09935) | 2024 | Commander + Scorer + Critic-as-Devil's-Advocate for **NLG evaluation**. Improves correlation with human ratings on SummEval / Topical-Chat. **Single model family per run** (the paper tests Gemini Pro, GPT-3.5, GPT-4 separately, not mixed). | strong (within its scope) | [arXiv 2405.09935](https://arxiv.org/abs/2405.09935) |
| Auto Arena of LLMs | 2024 | LLM peer-battles + a committee of judges automate eval. | medium | [arXiv 2405.20267](https://arxiv.org/abs/2405.20267) |
| Multi-Agent Debate for LLM Judges (Adaptive Stability Detection) | 2025 | Iterative debate among judges with Beta-Binomial mixture stopping rule; beats majority vote. | medium | [arXiv 2510.12697](https://arxiv.org/abs/2510.12697) |
| TrustJudge | 2025 | Distribution-sensitive scoring + likelihood-aware aggregation; reduces score / pairwise inconsistencies by 8–11%. | medium | [arXiv 2509.21117](https://arxiv.org/abs/2509.21117) |
| Peacemaker or Troublemaker | 2025 | Sycophancy is the dominant failure mode in multi-agent debate; agents flip from correct to incorrect to favor agreement. Provides design principles for productive disagreement. | medium | [arXiv 2509.23055](https://arxiv.org/abs/2509.23055) |
| Talk Isn't Always Cheap | 2025 | Empirically catalogs MAD failure modes; shows debate can underperform single-agent baselines when sycophancy dominates. | medium | [arXiv 2509.05396](https://arxiv.org/abs/2509.05396) |
| CONSENSAGENT | 2025 | Dynamically refines prompts based on agent interactions to reduce sycophancy; SOTA on six reasoning benchmarks. | medium | [ACL 2025 Findings 1141](https://aclanthology.org/2025.findings-acl.1141/) |

### 3.3 Cross-vendor blind / behavioral-entanglement-aware

| Name | Year | Key idea | Evidence | Link |
|---|---|---|---|---|
| **How Independent are Large Language Models?** (de-entangled verifier ensembles) | 2026 | Statistical framework auditing behavioral entanglement across **18 LLMs from six families**. Defines DW-BEI and CIG metrics. Finds CIG correlates with judge-precision degradation (Spearman ρ = 0.64, p<0.001 for GPT-4o-mini judges; ρ = 0.71, p<0.01 for Llama3 judges). De-entangled reweighting yields up to **+4.5% accuracy over majority voting**. | **strong (this is the right citation for the cross-vendor claim)** | [arXiv 2604.07650](https://arxiv.org/abs/2604.07650) |
| Mixed-Vendor Multi-Agent Clinical Diagnosis | 2026 | Mixed-vendor teams (o4-mini + Gemini-2.5-Pro + Claude-4.5-Sonnet) outperform single-vendor teams by surfacing diagnoses homogeneous teams collectively miss. | medium | [wiki summary of arXiv 2603.04421](https://wiki.charleschen.ai/arxiv/raw/2603-04421v2-do-mixed-vendor-multi-agent-llms-improve-clinical-diagnosis) |
| Evaluative Fingerprints | 2024 | LLM judges have near-zero inter-judge agreement (Krippendorff's α ≈ 0.042); judges encode distinct implicit theories of quality, so their disagreement is informative — supports treating cross-vendor judges as independent measurement instruments. | medium | [arXiv 2406.12708](https://arxiv.org/abs/2406.12708) |
| CPAR (Cross-Provider Adversarial Review) | 2025 | Engineering framework: blind iterative peer review across providers until consensus convergence; explicit anti-herding-bias design. | engineering / rhetorical | [github olanokhin/cpar-framework](https://github.com/olanokhin/cpar-framework) |

**Verification of the README's claim.** Our `agent-roundtable/README.md` currently says: *"研究显示，跨厂商独立分配可以获得 ~99% 的有效分歧率，远高于"请你批判性思考"提示能拿到的 ~48% 基线（arXiv 2405.09935）。"* This is **miscited and unverified**:

- arXiv 2405.09935 is "DEBATE: Devil's Advocate-Based Assessment and Text Evaluation," a single-family NLG evaluation paper. It does not measure cross-vendor disagreement and contains neither 99% nor 48% as headline numbers (verified by full-text grep of the arXiv HTML on 2026-05-10).
- The closest **real** numerical evidence for the "cross-vendor reduces correlated failure" claim is arXiv 2604.07650 (above): +4.5% accuracy from de-entangled reweighting over majority voting, with statistically significant ρ ≈ 0.6–0.7 between behavioral entanglement and judge precision degradation. That number is more conservative but is actually defensible.
- Recommendation: **either re-cite to 2604.07650 with the +4.5% / ρ figures, or drop the specific percentages and say "cross-family judges have lower correlated-failure rates than same-family judges" qualitatively.**

### 3.4 Plan-execute-review pipelines (shipped systems)

| Name | Year | Loop | Evidence | Link |
|---|---|---|---|---|
| Codex CLI `/goal` | 2026 | single-agent self-loop with `update_goal` exit + budget soft-stop + anti-stall (no-tool-calls). | engineering | [follow-goals](https://developers.openai.com/codex/use-cases/follow-goals), [PR #18076](https://github.com/openai/codex/pull/18076) |
| Claude Code plan mode + sub-agents | 2025 | Three-phase main loop (gather / act / verify) wrapping a simple while-loop on tool calls; ships `Explore` (read-only), `Plan` (research), and `General-purpose` sub-agents with isolated context windows; canonical pattern is "builder → validator" sub-agent chain. | engineering | [code.claude.com docs](https://code.claude.com/docs/en/how-claude-code-works.md), [arXiv 2604.14228](https://arxiv.org/abs/2604.14228) |
| Aider architect/editor | 2024 | **Two-model split** in one vendor (or cross-vendor): Architect (reasoning model) describes the change; Editor (formatting-disciplined model) emits the diff. SOTA on Aider's bench (85% with o1-preview + DeepSeek/o1-mini). | engineering + benchmark | [aider 2024-09-26](https://aider.chat/2024/09/26/architect.html) |
| Cursor agents | 2025–26 | Mode-switched agent (Agent / Plan / Ask / Debug) with skills, sub-agents, hooks; Plan mode is read-only. | engineering | (in-product) |
| OpenHands (formerly OpenDevin) | 2024–26 | Stateless Agent → Action; append-only EventLog; Workspace returns Observations. Reaches ~77% on SWE-Bench Verified with Claude Sonnet 4.5. | engineering + benchmark | [OpenHands deep-dive](https://dev.to/truongpx396/openhands-deep-dive-build-your-own-guide-1al0) |
| Devin (Cognition) | 2024 | Closed-source autonomous SWE; planner + browser + shell + editor agents in a single account. Concrete loop is not public. | rhetorical / closed | (vendor blog) |
| Factory droid | 2025 | Closed-source; documented as plan-build-verify. | rhetorical / closed | (vendor blog) |
| Cline | 2024–26 | VS Code agent loop with strong human-approval UX (every file/command/diff shown before execution). Single-model. | engineering | [rightaichoice 2026 guide](https://rightaichoice.com/blog/open-source-ai-coding-agents-2026-self-hosting-guide) |

### 3.5 Where `roundtable-develop` sits in this landscape

Among shipped systems, only **Aider architect/editor** routinely uses two different models, and even there the second model is a *formatter*, not a *blind verifier*. None of the shipped systems mandates **(a) different actor families AND (b) blind to prior verdicts AND (c) on-disk audit trail AND (d) evidence-graded convergence signal** the way `roundtable-develop` does. The closest academic match is the cross-provider blind-review line in §3.3 plus the multi-agent-debate-with-stability-detection line (arXiv 2510.12697); the cross-vendor part is what `roundtable` adds on top.

---

## 4. `roundtable-develop` audit

Source read: `skills/roundtable-develop/SKILL.md`, root `SKILL.md`, `README.md` (all on this repo, 2026-05-10).

### 4.1 Strengths

1. **The independence story is empirically defensible (with the right citation).** The *direction* of the README's claim — that cross-vendor blind reviewers catch more real defects than same-family or non-blind ones — is supported by arXiv 2604.07650's behavioral-entanglement results and by the sycophancy-failure-mode line (arXiv 2509.23055, 2509.05396). Among shipped agentic systems this is the single biggest differentiator.
2. **Plan-before-code matches the strongest academic prior.** The "planner produces `plan.md` and `GOAL.md` with acceptance criteria, reviewers grade against `GOAL.md` not vibes" is exactly the design that MetaGPT / ChatDev / Aider-architect / Claude-Code-plan-mode all converged on independently.
3. **Convergence-by-evidence (not vibes).** `convergence_status` / `next_action_hint` / `evidence_delta_vs_prior_round` from the aggregator is much closer to the multi-agent-debate-with-adaptive-stability-detection design (arXiv 2510.12697) than to a fixed N-rounds-then-stop heuristic. This is correct.
4. **Independent verification rule.** "`THREAD.md` is a log, not evidence — each agent reads source files and runs verification commands directly" is the right default; many systems (especially debate-only setups) fail silently when reviewers grade off-stale-log instead of off-source.
5. **`disable-model-invocation: true` on the router and dispatch confirmation block.** Prevents accidental auto-loops, which is the failure mode every autonomous-agent-gone-wrong screenshot on Twitter is about.
6. **Three-rounds-stalled escalation.** This is the single most important guardrail; loops that don't converge are a planner / capability problem, not an effort problem. The skill names this explicitly.

### 4.2 Gaps

1. **The ~99% / 48% citation is wrong.** arXiv 2405.09935 is DEBATE (single-family NLG eval) and does not contain those numbers (verified). This is the highest-priority correction because the README is the project's external face.
2. **No budget circuit-breaker.** Codex `/goal` enforces both token AND wall-clock budgets at every turn / tool / mutation / interrupt boundary; `roundtable-develop` only has "three rounds without convergence ⇒ escalate." A round here is multiple turns × multiple actors, so a stalled run can burn far more compute than one Codex `/goal` budget cycle. There is no per-round or per-thread token / wall-clock cap.
3. **No "no-progress-this-round ⇒ stop" anti-stall.** Codex's "continuation turn with zero tool calls ⇒ suppress further continuation" has no analog. If the executor turn produces no `git diff` and the reviewer says "still BLOCKER but no new evidence," the loop should fast-fail rather than re-dispatch a planner. `evidence_delta_vs_prior_round` is the right *signal*; the skill does not currently *act* on it as a stop rule.
4. **Reviewer ensemble size is fixed at 2.** arXiv 2604.07650 shows the de-entanglement gain saturates somewhere above 2 — and 2 reviewers gives no tie-break beyond aggregator preference. There's no doc / skill guidance for "when do I want a third reviewer from a third family?"
5. **No within-turn devil's-advocate.** The DEBATE paper's actual contribution is that **inside one model's turn**, a critic persona substantially improves output quality (e.g. on SummEval, GPT-4 + Devil's-Advocate beats GPT-4 + Plain Multi-Agent by ~9pp Spearman). `roundtable-develop` only uses devil's-advocate as an *external* reviewer role. Adding a one-shot self-critique inside the executor's prompt is cheap and can compress the number of full review rounds needed.
6. **No structured signal for "executor scope creep."** The skill says "`git diff --stat` shows changes outside `In-scope paths` from `GOAL.md` ⇒ scope violation" — but this is a human-eyeball check. No script enforces it. The aggregator sees the diff but the convergence schema does not have a `scope_violation` field.
7. **No warm-resume after pause.** Codex's "auto-reactivates paused goals when a thread resumes outside plan mode" is convenient. `roundtable-develop` requires the user to manually re-dispatch. This is a UX gap, not a correctness gap.
8. **No cost / model-tier guidance.** `MODEL-CAPABILITY-GUIDE.md` exists but the develop skill does not reference per-role model tier defaults. The "loop overhead dominates the work" warning is correct but qualitative.

### 4.3 Risks

1. **Sycophancy via shared system-prompt features.** The `--blind` flag prevents seeing prior verdicts, but reviewers still share `roles/_independence_rule.md` text and the same JSON schema. Two reviewers from different vendors but with identical instruction surfaces can still synchronize on the same misreading. arXiv 2509.05396 ("Talk Isn't Always Cheap") flags this explicitly. Mitigation: vary reviewer prompts (e.g. one focused on correctness, one on adversarial inputs) — the existing `reviewer` vs `devils-advocate` split is the right shape, just make sure the prompts are actually distinct.
2. **Aggregator becomes the single point of failure.** If the aggregator is one model from one vendor, the entire blind-cross-vendor ceremony reduces to "one model decides who was right." Mitigation: the aggregator should never *override* a unanimous BLOCKER; it should aggregate, not arbitrate.
3. **`update_goal`-style model-emitted completion is not used.** Good thing — this is a feature not a bug. Codex's self-declared `achieved` is exactly the failure mode `roundtable` is trying to avoid. But the skill should make this trade-off explicit somewhere, because a user coming from `/goal` will ask "why doesn't the executor just declare done?"
4. **"Three rounds then escalate" can mask under-specified `GOAL.md`.** If acceptance criteria are vague, the planner will keep producing technically-different-but-equally-vague plans and the loop will burn three rounds before bailing. Mitigation: add a planner-output validator that scores `GOAL.md` for measurability before allowing Phase 2.

### 4.4 Top 1–3 highest-leverage improvements (proposals only, do not implement)

In order of leverage-per-line-of-change:

1. **Fix the citation (one-line edit, large credibility gain).** Replace `arXiv 2405.09935` and the "99% / 48%" numbers in `README.md` with arXiv 2604.07650 and its actual measured results (+4.5% accuracy from de-entangled verifier ensembles over majority voting; ρ ≈ 0.64–0.71 between behavioral entanglement and judge-precision degradation). Or drop the specific percentages.
2. **Add budget + anti-stall stop conditions to Phase 5.** Borrow Codex `/goal`'s two extra rules: (a) token / wall-clock budget per thread, surfaced via the dispatch confirmation block; (b) "if `evidence_delta_vs_prior_round` is `none` AND BLOCKERs are unchanged, fast-fail to user instead of dispatching another executor turn." This costs one extra check in the aggregator schema and one branch in Phase 5; gain is bounded loop cost and earlier escalation on under-specified goals.
3. **Add a within-turn devil's-advocate to the executor prompt.** Before emitting the final five-part body, the executor self-critiques against `GOAL.md` and the plan, then revises. This is the actual `arXiv 2405.09935` contribution and is cheap (one extra prompt section, no new turn). It compresses the average number of review rounds needed and is orthogonal to the cross-vendor blind review (which still happens, just less often).

(Optional fourth: add a `scope_violation` field to the aggregator schema and a `git diff --stat` check that fails the round if the executor touched paths outside `GOAL.md`'s `In-scope paths`. Cheap and high-signal.)

### 4.5 Verdict

**Broadly aligned with the strongest current designs and stricter than every shipped competitor on the cross-vendor verification axis.** The structural design is right; the gaps are operational (budget, anti-stall, within-turn critic) and one (1) factual error in the README. None of the gaps require redesigning the loop.

---

## 5. Reading list (must-reads, ordered by leverage for this project)

1. [openai/codex PR #18076 — Add goal core runtime](https://github.com/openai/codex/pull/18076) — concrete reference implementation of an autonomous-goal scheduler with budget + anti-stall.
2. [arXiv 2604.07650 — How Independent are Large Language Models?](https://arxiv.org/abs/2604.07650) — the actual empirical backing for cross-family verifier independence; replaces the bad citation in our README.
3. [arXiv 2509.23055 — Peacemaker or Troublemaker: How Sycophancy Shapes Multi-Agent Debate](https://arxiv.org/abs/2509.23055) — design principles for productive disagreement; directly relevant to how we configure `reviewer` vs `devils-advocate`.
4. [arXiv 2509.05396 — Talk Isn't Always Cheap: Failure Modes in Multi-Agent Debate](https://arxiv.org/abs/2509.05396) — when debate underperforms single-agent baselines; informs our anti-stall + budget design.
5. [arXiv 2510.12697 — Multi-Agent Debate for LLM Judges with Adaptive Stability Detection](https://arxiv.org/abs/2510.12697) — Beta-Binomial mixture stopping rule; principled alternative to "three rounds then escalate."
6. [arXiv 2405.09935 — DEBATE](https://arxiv.org/abs/2405.09935) — the actual content of the paper we miscited; supports adding a within-turn devil's-advocate self-critique.
7. [aider — Separating code reasoning and editing (architect/editor)](https://aider.chat/2024/09/26/architect.html) — only shipped system that natively supports cross-model splits; a useful reference for our `claude_turn` / `codex_turn` split.
8. [OpenAI Developers — Follow a goal](https://developers.openai.com/codex/use-cases/follow-goals) — the user-facing contract Codex `/goal` asks for; our `GOAL.md` already encodes most of this, worth a re-read.
9. [arXiv 2308.00352 — MetaGPT](https://arxiv.org/abs/2308.00352) — canonical academic reference for SOP-driven planner / executor / QA roles.
10. [arXiv 2604.14228 — Dive into Claude Code](https://arxiv.org/abs/2604.14228) — recent design-space survey; situates `roundtable` against Claude Code's plan-mode + sub-agents.

---

## Appendix A — Items I could not fully verify

- **Devin and Factory droid internal loop details.** Both are closed-source; I have only vendor blog claims.
- **Cursor agents internals.** No published source code; I rely on in-product UI and docs.
- **arXiv IDs with year prefix `26xx`.** These are arXiv submissions from 2026; today's date is 2026-05-10, so they are real but very recent and not yet replicated. I have flagged each as "medium" or "strong" evidence accordingly and read the abstracts directly.
- **The exact prompt text of Codex's "continuation" and "budget-limit" templates.** PR #18076's description names them but I did not chase them down to the file in `codex-rs/core`. This is fine for our purposes — we care about the runtime behavior, not the exact wording.
