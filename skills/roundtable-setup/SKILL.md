---
name: roundtable-setup
description: Use when the user asks to set up, initialize, or configure agent-roundtable, when `models.json` is missing, or when a project lacks `AGENTS.md` / `CLAUDE.md` for full-blood agent boot.
disable-model-invocation: true
---

# Roundtable Setup

Bring a fresh checkout of `agent-roundtable` to a state where any sub-skill can dispatch a turn against the user's project — credentials live on disk in chmod-600 files, model registry is populated, and the project root has `AGENTS.md` / `CLAUDE.md` so each agent CLI boots with full project awareness instead of re-discovering the codebase from scratch.

## Use when

- `models.json` is missing or contains only the `_template` entry.
- The user says "set up", "initialize", "configure", "import a model", "switch backend".
- A sub-skill (`roundtable-plan`, `roundtable-review`, `roundtable-execute`, `roundtable-goal`) refused to dispatch because `models.json` is absent.
- The user's project has no `AGENTS.md` and you are about to run a multi-turn flow against it.

## Don't use when

- `models.json` already has the actor the user wants and `backend.sh show` reports `ok`. Skip to the actual task.
- The user only wants to add a single one-shot model; a direct `backend.sh codex|claude <base-url> <api-key>` call is enough — full init walkthrough is overkill.

## Why this matters

Agent CLIs explore from their CWD on every turn. Without project context files at the project root, each turn pays a re-discovery tax in tokens **and** drifts on conventions. `AGENTS.md` is read by Codex, Cursor, and most CLIs at boot; `CLAUDE.md` adds Claude-specific guidance via `@AGENTS.md` import. Generating these once at init is the difference between a full-blood agent and one that re-learns the project every turn.

## The process

### 0. Confirm the project root (REQUIRED)

Use the `AskQuestion` tool — do NOT emit prose. Pre-fill the candidates from `git rev-parse --show-toplevel` and any open IDE folders so the user clicks instead of typing.

```
AskQuestion(
  prompt="Which directory is your PROJECT root? (NOT the skill itself.)",
  options=[
    {id: "<auto-detected git toplevel>",  label: "<git toplevel> (auto-detected)"},
    {id: "<currently open folder>",       label: "<currently open folder>"},
    {id: "__custom__",                    label: "Other — I'll type it"},
  ],
)
```

If `__custom__`, follow up with a second `AskQuestion` that lists up to 5 recently seen git toplevels (obtained via `git rev-parse --show-toplevel` and any IDE workspace roots) plus a final `{id: "__type-it__", label: "其他 — 我来输入路径"}` option. If the user selects `__type-it__`, prompt for a free-form path in a follow-up message. Do NOT open a shell prompt for path collection. Validate before moving on:

```bash
export ROUNDTABLE_PROJECT_ROOT=<chosen path>
[[ -d "$ROUNDTABLE_PROJECT_ROOT" && "$ROUNDTABLE_PROJECT_ROOT" != *"/skills/agent-roundtable"* ]] \
  || { echo "ERROR: invalid or = skill itself" >&2; }
```

Threads then land at `$ROUNDTABLE_PROJECT_ROOT/.roundtable/threads/<slug>/`. Persistence (one-time): suggest user add `export ROUNDTABLE_PROJECT_ROOT=...` to `~/.bashrc` / `~/.zshrc`.

Why this is REQUIRED: without the env var, `_common.sh` falls back to `git rev-parse` from the parent's `cwd`. When that cwd is the skill itself (common when answering questions about it), every turn emits `WARN: ROUNDTABLE_PROJECT_ROOT is the skill's own directory` and agents explore the skill, not the user's project.

### 1. Seed `models.json`

Run:

```
bash $SKILL/scripts/backend.sh init
```

This writes `$SKILL/models.json` (chmod 600, gitignored) and prints a walkthrough explaining the four user-fillable fields per model: `actor`, `cli_arg`, `endpoint.base_url`, `endpoint.api_key`. Tell the user to open the file and replace the `_template` entry with their real model(s). Then call:

```
AskQuestion(
  prompt="models.json 编辑完成了吗？",
  options=[
    {id: "applied",       label: "已保存，继续"},
    {id: "still-editing", label: "还在编辑，稍等"},
    {id: "need-template", label: "帮我填一个示例 actor"},
    {id: "cancel",        label: "取消 setup"},
  ],
)
```

- `still-editing` → wait and re-show the same `AskQuestion`.
- `need-template` → paste a minimal example actor block from `models.example.json`, then re-show the `AskQuestion`.
- `cancel` → abort setup.

### 2. Apply

After the user signals completion ("done", "applied", or similar):

```
bash $SKILL/scripts/backend.sh apply
bash $SKILL/scripts/backend.sh show
```

`apply` performs three things in order: (a) **static check** — reject known-bad combinations like `cli_arg: "opus"` paired with a proxy `base_url` (e.g. `claude-api.org`) before writing any file; (b) write `$SKILL/.codex_env.local` and/or `$SKILL/.claude_env.local` (chmod 600); (c) **smoke test + latency** — send one 1-token ping per actor (and per claude tier model if distinct), record `elapsed_ms`, fail-fast on 4xx/5xx, then print a **latency summary sorted fastest first**. Entries `≥2000 ms` tagged `[SLOW]`, `≥5000 ms` tagged `[VERY SLOW]` — surface these to the user; they often mean the proxy is degraded or geographically far. Pass `--no-smoke-test` to skip step (c) (offline / air-gapped scenarios). `show` then prints redacted state. For a re-check without rewriting env files: `backend.sh validate` (same latency display).

If `apply` rejects a combination at step (a), the error message points at the exact `cli_arg` field to fix — change the short alias to the proxy-precise model id (see Provider quirks below).

### 3. Generate project context (only if missing)

If `$ROUNDTABLE_PROJECT_ROOT/AGENTS.md` does not exist, call:

```
AskQuestion(
  prompt="项目根没有 AGENTS.md，要生成吗？",
  options=[
    {id: "generate",        label: "生成 AGENTS.md + CLAUDE.md"},
    {id: "skip",            label: "跳过 (后续 turn 不带项目上下文)"},
    {id: "let-me-look",     label: "先让我看看现有文件"},
  ],
)
```

If the user selects `generate`:

- Read `README.md`, top-level dirs, any `.planning/` index files.
- Write `AGENTS.md` at the project root with cross-platform rules: build commands, directory map, PR rules, code style, do-not-touch paths.
- Write `CLAUDE.md` at the project root containing exactly:

  ```
  @AGENTS.md

  ## Claude Code Specifics
  - Default to `plan` mode for review tasks.
  ```

Explain that subsequent dispatches will boot with full project awareness.

### 4. Seed `.claude/settings.json` (only if missing)

If `$ROUNDTABLE_PROJECT_ROOT/.claude/settings.json` does not exist, call:

```
AskQuestion(
  prompt=".claude/settings.json 不存在，怎么处理？",
  options=[
    {id: "copy-template", label: "从模板复制 (推荐：包含拒绝破坏性 git 和 secrets 读取规则)"},
    {id: "skip",          label: "跳过"},
    {id: "diff-existing", label: "对比现有文件，只推荐缺失规则"},
  ],
)
```

If the user selects `copy-template`, copy the template:

```bash
mkdir -p "$ROUNDTABLE_PROJECT_ROOT/.claude"
cp "$SKILL/templates/.claude/settings.json" "$ROUNDTABLE_PROJECT_ROOT/.claude/settings.json"
```

The template denies destructive git operations (`git push`, `git reset --hard`, `git rebase`, `git filter-branch`, `git update-ref`) and reads of common secrets (`.env*`, `~/.aws/**`, `~/.ssh/**`, `credentials*`, `*secret*`, `*.pem`). With this file present, `claude_turn.sh` skips its inline `--disallowedTools` fallback in favour of project-level settings — same coverage, source-controllable, user-overridable.

If the user selects `diff-existing` (settings file already present), read the existing file and recommend additions for any of the above deny rules that are missing; **do not overwrite**.

## Provider quirks (read before filling `cli_arg`)

The CLIs (`codex` / `claude`) accept short model aliases — `"opus"`, `"sonnet"`, `"gpt-5"` — and silently resolve them to a current dated slug (e.g. `claude-opus-4-5-20250929`) before sending the API request. **Official vendors** (`api.anthropic.com`, `api.openai.com`) accept those resolved slugs. **Proxies** (`claude-api.org`, `cialloapi.cn`, DeepSeek-shim, OpenRouter, etc.) do **not** do alias resolution — they reject any model id they don't recognise verbatim, returning 502 / 503 with bodies like `"No available accounts"` (per [claude-api.org FAQ §503](https://doc.claude-api.org/faq)).

This produces a setup-time footgun: the user copies an example with `cli_arg: "opus"` and `base_url: "https://api.anthropic.com"`, then later flips `base_url` to a proxy without realising `cli_arg` has to flip too. The `apply` static check now catches the most common combinations of this:

| `base_url` host | Disallowed `cli_arg` (will be rejected) | Use instead |
|---|---|---|
| `claude-api.org` | `opus`, `sonnet`, `haiku` | `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5` (or whatever's in the [channel doc](https://doc.claude-api.org/channels)) |
| `cialloapi.cn` | `gpt-5`, `gpt-4`, `o1`, `o3` (no version suffix) | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, etc. |
| `*.deepseek.com/anthropic` | `opus`, `sonnet`, `haiku` | the upstream id, e.g. `deepseek-v4-pro[1m]` |
| `openrouter.ai/api/v1` | any short alias | the OpenRouter-namespaced id, e.g. `anthropic/claude-opus-4` |

If you're using a proxy not on this list, **always** consult the proxy's accepted-model doc and use the exact id. The smoke test (step 2c above) catches everything else.

### 5. Warm up the research cache (only if a thread exists)

After `backend.sh apply` succeeds, if a thread directory already exists (i.e. the user is re-running setup against an ongoing thread), pre-warm the research cache so the first dispatch does not trigger a redundant freshness check:

```bash
python3 $SKILL/scripts/lib/research_cache.py --thread <slug>
```

If no thread exists yet this step is skipped — the cache will be written on the first `roundtable-plan` / `roundtable-execute` dispatch.

## Stop when

- `ROUNDTABLE_PROJECT_ROOT` is exported to a real directory **and** is NOT the skill itself. Verify with `echo "$ROUNDTABLE_PROJECT_ROOT" && [[ -d "$ROUNDTABLE_PROJECT_ROOT" ]] && echo OK`. The turn scripts emit a `WARN` if confused; act on it.
- `backend.sh show` reports the actor(s) the user needs as `ok`.
- The project has `AGENTS.md` (and `CLAUDE.md` if the user uses Claude Code).
- The project has `.claude/settings.json` with the agent-roundtable deny rules (or an explicit user-customised superset).

## Hand off

After setup succeeds, point the user at the next sub-skill that matches their actual goal:

- "Run `import_plan.sh /path/to/plan.md` if execution should follow a Cursor plan (auto-creates a thread with the right slug), then `roundtable-execute`."
- "Now you can run `roundtable-plan` to research options or build an executable PLAN.md."
- "Now you can run `roundtable-review` for a cross-vendor review."
- "Now you can run `roundtable-execute` to implement PLAN.md with a single executor (advanced N-parallel race in docs/advanced.md)."
- "Now you can run `roundtable-goal` for a planner→executor→reviewer convergence loop."

Do not auto-dispatch — wait for the user to state the task.
