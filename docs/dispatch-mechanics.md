# Dispatch Mechanics

> Reference for all sub-skills. Details on how the chat parent assembles a Dispatch Confirmation block, permission tiers by role, and how to recalibrate token budgets.

## Estimator and recalibration

The chat parent MUST run `route.sh ... --estimate` (or `scripts/lib/estimate_cost.py --model <alias> --role <role>` directly) before showing the confirmation; do not hand-estimate. Token *rates* in `models.json` are correct — past 20x undercounts came from guessing token *counts* for thinking-mode and agentic turns. The estimator's heuristic table lives at the top of `scripts/lib/estimate_cost.py` and is the auditable contract. After each turn completes, `codex_turn.sh` / `claude_turn.sh` append a record to `$ROUNDTABLE_PROJECT_ROOT/.roundtable/usage.log`; run `python3 scripts/recalibrate_token_budgets.py --since-days 30` quarterly to retune the heuristic against actual usage (`--apply` rewrites the budget table in place between sentinel comments). Pricing for non-Cursor models can also be cross-checked against the vendored LiteLLM snapshot via `--source snapshot`; refresh with `python3 scripts/refresh_pricing_snapshot.py`.

Sub-skills cite this block by name. Do not duplicate it elsewhere.

## Generating the Dispatch Confirmation block (Hard Rule #2)

The chat parent MUST invoke `python3 scripts/print_dispatch_block.py --model <alias> --role <role> [--effort <e>] [--thread <slug>] [--project <path>]` and paste its stdout verbatim into the Dispatch Confirmation. The script reads `models.json` directly, delegates pricing/estimate to `route.py`, and explicitly excludes deprecated foot-gun keys (`_official_before_discount` / `_pretax_reference`). Do NOT compose the block by hand; the chat parent has misquoted pricing twice in this skill's history when allowed to "remember" the registry.

The block now contains both `Alias` (key in `models.json`) and `Route` (Claude Code CLI vs Codex CLI vs Cursor subagent + base_url) so the two paths to the same vendor model can't be conflated — see root SKILL.md "Mechanics" → *Route disambiguation*.

## Permission tiers by role (Mechanics, not a hard rule)

Three permission tiers, vendor-enforced:

- **Reviewer / planner / discussant-style** roles → read-only: Claude `--permission-mode plan`, Codex `--sandbox read-only`, Cursor subagent `Task(readonly:true)`. Planner output is captured under `artifacts/plan-<actor>-*.md`.
- **Executor** roles → Claude `--permission-mode dontAsk` + explicit allow list in `<project_cwd>/.claude/settings.json` (Bash for chmod / git status,diff,add,commit / python3 / scripts; deny destructive git + secret reads). Headless `claude -p` cannot answer permission prompts, so allow-list IS the contract — `default` / `acceptEdits` deny most Bash silently. Codex executor → `--sandbox workspace-write` with deny on destructive git.
- **Other roles** → Claude `acceptEdits` + same `.claude/settings.json` deny list.

`<project_cwd>/.claude/settings.json` is the single source of truth (Anthropic docs: `--add-dir` paths do NOT contribute settings; cwd-anchored). `roundtable-setup` copies `templates/.claude/settings.json` into the user's project root; the skill repo also ships a sibling `.claude/settings.json` for self-audits.

## Silent quality filter

`route.py` silently removes candidates whose `endpoint.quality.format_compliance == "fail"` from any role except `discussant` (which does not require the 5-part turn body). If a model is missing from routing suggestions after `backend.sh measure` runs, check the quality block:

```bash
python3 scripts/lib/route.py --role executor --json | python3 -c "import json,sys; print(json.load(sys.stdin))"
# Or run measure again:
bash scripts/backend.sh measure
```

Models with no `endpoint.quality` data (never measured) are kept as unverified candidates, not dropped.
