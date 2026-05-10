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

### 1. Seed `models.json`

Run:

```
bash $SKILL/scripts/backend.sh init
```

This writes `$SKILL/models.json` (chmod 600, gitignored) and prints a walkthrough explaining the four user-fillable fields per model: `actor`, `cli_arg`, `endpoint.base_url`, `endpoint.api_key`. Tell the user to open the file, replace the `_template` entry with their real model(s), and reply when done.

### 2. Apply

After the user signals completion ("done", "applied", or similar):

```
bash $SKILL/scripts/backend.sh apply
bash $SKILL/scripts/backend.sh show
```

`apply` writes `$SKILL/.codex_env.local` and/or `$SKILL/.claude_env.local` (chmod 600) — these are sourced by the turn scripts at dispatch time. `show` prints redacted state so the user can verify import without leaking the API key.

### 3. Generate project context (only if missing)

If `$ROUNDTABLE_PROJECT_ROOT/AGENTS.md` does not exist, offer to generate it. If the user accepts:

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

If `$ROUNDTABLE_PROJECT_ROOT/.claude/settings.json` does not exist, copy the template:

```bash
mkdir -p "$ROUNDTABLE_PROJECT_ROOT/.claude"
cp "$SKILL/templates/.claude/settings.json" "$ROUNDTABLE_PROJECT_ROOT/.claude/settings.json"
```

The template denies destructive git operations (`git push`, `git reset --hard`, `git rebase`, `git filter-branch`, `git update-ref`) and reads of common secrets (`.env*`, `~/.aws/**`, `~/.ssh/**`, `credentials*`, `*secret*`, `*.pem`). With this file present, `claude_turn.sh` skips its inline `--disallowedTools` fallback in favour of project-level settings — same coverage, source-controllable, user-overridable.

If the user already has a `.claude/settings.json`, **do not overwrite**. Diff the deny list and recommend additions if any of the above are missing.

## Stop when

- `backend.sh show` reports the actor(s) the user needs as `ok`.
- The project has `AGENTS.md` (and `CLAUDE.md` if the user uses Claude Code).
- The project has `.claude/settings.json` with the agent-roundtable deny rules (or an explicit user-customised superset).
- `ROUNDTABLE_PROJECT_ROOT` resolves to the user's project — never to the skill's own directory. The turn scripts emit a `WARN` if confused; act on it.

## Hand off

After setup succeeds, point the user at the next sub-skill that matches their actual goal:

- "Now you can run `roundtable-plan` to research options or build an executable PLAN.md."
- "Now you can run `roundtable-review` for a cross-vendor review."
- "Now you can run `roundtable-execute` to implement PLAN.md with a single executor (advanced N-parallel race in docs/advanced.md)."
- "Now you can run `roundtable-goal` for a planner→executor→reviewer convergence loop."

Do not auto-dispatch — wait for the user to state the task.
