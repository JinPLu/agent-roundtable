# Model Capability Guide

> How to get the best out of each actor and avoid common pitfalls.  
> See `models.json` for current registry; `models.example.json` for full catalog.

---

## Actors at a glance

| Actor | Best at | Watch out for |
|-------|---------|---------------|
| **Codex CLI** (`codex`) | Repo-grounded execution; structured JSONL trace; goal bridge (`get_goal` / `create_goal` / `update_goal`) built-ins | Default timeout 1800s may cut very long reasoning chains; final message **must be only** the five-part body |
| **Claude CLI** (`claude`) | Careful review with constrained tools; `plan` permission mode for read-only reviewer roles; `--bare` for isolation | Default timeout 1500s; Anthropic-compat shims (e.g. DeepSeek) can have long tail latency; tool allowlist may block a legitimate read-only command |
| **Cursor subagent** (`cursor-subagent`) | Any Cursor-billed model (Gemini, Sonnet, Opus, Composer); highest SWE-bench scores available; good aggregator | No timeout cap in skill; Cursor task queue latency unbounded; prompts must be **fully self-contained** (no shared chat history) |

---

## Model registry (current defaults from `models.json`)

| Alias | Actor | Underlying | Context | Best for |
|-------|-------|-----------|---------|---------|
| `codex-gpt-5` | codex | GPT-5.5 (cialloapi) | 1M tok | Executor, fast reviewer companion |
| `claude-opus` | claude | DeepSeek-V4-Pro | 128K tok | Reviewer, discussant; cheap companion |
| `cursor-composer-2` | cursor-subagent | Composer-2 | 200K tok | Planner, executor |
| `cursor-claude-4.7-opus` | cursor-subagent | Claude Opus 4.7 (thinking-high) | 200K tok | Aggregator, hard reviewer |
| `cursor-claude-4.6-sonnet` | cursor-subagent | Claude Sonnet 4.6 (thinking-medium) | 200K tok | Reviewer, executor |
| `cursor-gemini-3.1-pro` | cursor-subagent | Gemini 3.1 Pro | 1M tok | Long-context tasks, SWE-bench agentic |

---

## Writing effective prompts

### 1. Put ground truth in `GOAL.md`, not the addendum

`GOAL.md` is injected into every turn. Put objective criteria, verification commands, and scope there. Use `--addendum` for turn-specific deltas only.

### 2. The five-part block must be the **entire** final message

```
## Turn N

**Summary**
...

**Read**
...

**Plan**
...

**Verification**
```json
{ ... }
```

**Next**
...
```

Any preamble before this block breaks `append_turn.sh` parsing.

### 3. Reviewers: put JSON first in Verification

`extract_json_verdict` greps for the first ` ```json ` block inside `**Verification**`. If the JSON is preceded by prose, extraction may fail silently.

### 4. Always pass `-m MODEL` explicitly

`resolve_model` in `_common.sh` has a known schema mismatch and will raise `AttributeError` if called without `-m`. Until the bug is fixed, always pass the model flag:

```bash
bash scripts/codex_turn.sh SLUG --role executor -m gpt-5.5 ...
bash scripts/claude_turn.sh SLUG --role reviewer -m deepseek-v4-pro\[1m\] ...
```

### 5. Use workspace-absolute paths for addendum files

In Cursor sandboxes, `/tmp` paths may be inaccessible to the script. Use `--addendum-file /full/path/to/file`.

---

## Multi-agent patterns

### Blind parallel review (anti-sycophancy)

Use `--blind` on all parallel reviewers. This suppresses the prior verdict from their prompt, reducing the 85% modal adoption rate observed when reviewers see a prior strong verdict.

```bash
# Parallel blind reviewers
bash scripts/codex_turn.sh SLUG --role reviewer -m gpt-5.5 --blind &
bash scripts/claude_turn.sh SLUG --role reviewer -m deepseek-v4-pro\[1m\] --blind &
wait
# Aggregator sees all verdicts
bash scripts/codex_turn.sh SLUG --role reviewer-aggregator -m gpt-5.5
```

**Do NOT use `--blind` on the aggregator** — it needs to see all verdicts to select the most defensible one.

### Cheap companion alongside expensive dispatch (Principle A)

When dispatching a mid-tier or expensive model, always run a cheap cross-vendor companion in parallel for the same role. The companion uses `--blind`.

```bash
# Expensive primary
bash scripts/codex_turn.sh SLUG --role executor -m gpt-5.5 &
# Cheap companion (different vendor, blind)
bash scripts/claude_turn.sh SLUG --role reviewer -m deepseek-v4-pro\[1m\] --blind &
wait
```

Disagreement between the two is a quality signal — surface it to the user; do not discard it.

**Skip for:** trivial tasks (single file read, typo fix). Use for: any execution with side effects or significant scope.

### Devil's advocate

Use when consensus is suspicious or stakes are high. Assign to a cheap model (cost-efficient adversarial coverage).

```bash
bash scripts/claude_turn.sh SLUG --role devils-advocate -m deepseek-v4-pro\[1m\] --blind
```

Note: `append_turn.sh` currently does not extract verdict JSON for `devils-advocate`. The turn will land in `THREAD.md` but `verdict.json` won't be written. Use `codex_turn.sh` or `claude_turn.sh` directly (they do extract it).

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

## Cost reference (snapshot — verify before large runs)

| Model | Input $/M | Output $/M | Notes |
|-------|----------|-----------|-------|
| GPT-5.5 (cialloapi) | ~$0.069 | ~$0.069 | ~70x cheaper than official OpenAI |
| DeepSeek-V4-Pro | ~$0.14 | ~$0.87 | Via Anthropic-compat; check `_as_of` in models.json |
| Cursor-billed models | Billed to Cursor account | — | No per-token charge outside Cursor |

> Pricing changes frequently. Always check `models.json` `pricing._as_of` and re-research if > 30 days old.
