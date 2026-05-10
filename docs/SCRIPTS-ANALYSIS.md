# Scripts Analysis

> Deep-dive on every script in `scripts/`.  
> Focus: what is hard-coded vs. flexible, what can be replaced by agent autonomy, what must stay deterministic.

---

## `_common.sh`

### What it does (step by step)

1. Resolves `ROUNDTABLE_REPO_ROOT` via `git rev-parse --show-toplevel`
2. Derives `ROUNDTABLE_ROOT`, `THREADS_ROOT`, `SKILL_DIR` from root
3. Defines `load_actor_env` (sources `.codex_env.local` / `.claude_env.local`)
4. Defines `build_prompt`:
   - Stable prefix (role identity)
   - Injects `GOAL.md`
   - Injects repo context
   - Injects optional thread summary
   - Injects last K turns via `compact_recent_turns.py`
   - Injects optional latest verdict block (skipped if `--blind`)
   - Injects `OPEN_QUESTIONS.md`
   - Appends role system markdown
   - Appends addendum
5. Defines `resolve_model` — reads `models.json`, looks up `role_defaults[role]` for actor
6. Defines `write_meta`, `emit_done`, worktree helpers, `extract_json_verdict`

### Hard-coded vs. flexible

| Concern | Hard-coded | Flexible |
|---------|-----------|---------|
| Repo root detection | `git rev-parse` (correct) | `ROUNDTABLE_REPO_ROOT` env override |
| Tail size | Default `ROUNDTABLE_TAIL_K=3` | `ROUNDTABLE_TAIL_K` env |
| Verification truncation | ~1000 chars (in Python script) | `ROUNDTABLE_VERIFICATION_LIMIT` env |
| Blind mode | `ROUNDTABLE_SKIP_LATEST_VERDICT=1` | Set by `--blind` in turn scripts |
| Prompt structure | Order of sections fixed | Sections present/absent by env |

### Can agent autonomy replace it?

**No.** Deterministic prompt assembly improves cache stability and reproducibility. An LLM assembling its own prompt from scratch would be non-reproducible and token-wasteful. The critical pieces to keep: `emit_done` contract, secret-free logging, git root detection.

---

## `codex_turn.sh`

### What it does

1. Parse args (`--role`, `-m`, `--effort`, `--sandbox`, `--blind`, `--worktree`, `--addendum`, `--timeout-s`)
2. Validate addendum file readable
3. Call `resolve_model` if no `-m` (resolves first alias in `role_defaults[role]` whose `actor` matches `codex`)
4. Set sandbox default (`workspace-write`)
5. Create `history/codex/<timestamp>/` directory
6. Optional: create or switch to git worktree
7. Merge task addendum + optional **goal bridge** lines (for executor role: `get_goal`, `create_goal`, `update_goal` built-ins)
8. Call `build_prompt` (respects `--blind`)
9. Run `timeout $TIMEOUT codex exec --json ...` with output to `trace.jsonl`
10. Salvage `last.md` from trace (even on timeout/crash)
11. Append five-part turn block to `THREAD.md`
12. Extract verdict JSON for reviewer roles
13. `write_meta` + `emit_done`

### Hard-coded

- `approval_policy=never` — no user confirmation inside Codex session
- `goals` enabled for executor (goal bridge injected)
- Default timeout 1800s
- Sandbox default `workspace-write`

### Flexible

`-m`, `--effort`, `--timeout-s`, `--blind`, `--worktree`, `--sandbox`, addendum (text or file)

### What must stay scripted

Subprocess isolation, deterministic `ROUNDTABLE_DONE` signal, API key loading from env file, exit-code capture, and salvage — all require deterministic shell orchestration, not LLM judgment.

---

## `claude_turn.sh`

### What it does

Similar to `codex_turn.sh` with Claude-specific differences:

1. Parse args (same role set as today; no interactive `--permission-mode` override in the stock script)
2. `resolve_model` (resolves first alias in `role_defaults[role]` whose `actor` matches `claude`)
3. Set `permission-mode` default by role:
   - `reviewer`, `reviewer-aggregator`, `devils-advocate`, **`planner`**: `plan` (read-only; no workspace writes)
   - all other roles: `acceptEdits`
4. **Tool / disallowed list** by role: reviewer-likes and **planner** get no extra `disallowedTools` line; executor and discussant get destructive-git `disallowedTools` patterns (minimal disablement; `plan` mode is the main write guard for planner/reviewer).
5. Set `ROUNDTABLE_SKIP_ROLE_SYS=1` — role file passed as `--append-system-prompt` (not injected twice)
6. Run `timeout $TIMEOUT claude -p … --output-format json` with `--permission-mode` as above; stdout is the JSON blob, written to `last.json`
7. Extract final text via `jq` or `extract_claude_result.py` into `last.md`
8. **Planner + `plan` mode:** copy `last.md` to `artifacts/plan-claude-<ts>.md` so operators get a file even though the model could not write `artifacts/` itself
9. Append turn, extract verdict (reviewer roles), meta + done

### Hard-coded

- `plan` permission for reviewer-like roles and **planner**; `acceptEdits` for executor and discussant
- Executor / discussant: destructive git command patterns in `disallowedTools`
- Default timeout 1500s

### Flexible

`--model`, `--blind`, `--timeout-s`, `--task` / `--task-file`, per-turn addendum; no first-class flag to override permission mode in the stock script (change role or edit the script)

### Capability impact

**Planner `plan` mode:** the model must put its full plan in the assistant message; file writes under `artifacts/` are performed by the shell (`artifacts/plan-claude-*.md`). Reviewers remain read-only via the same permission mode.

---

## `route.sh` / `scripts/lib/route.py`

### What it does

1. Load `models.json` (falls back to `models.example.json`)
2. List aliases registered for the requested role
3. Filter to **available** actors (detects `codex` login via `codex auth status`, Claude via `ANTHROPIC_AUTH_TOKEN`, Cursor always available)
4. Apply scoring signals:
   - `--cost` → prefers cheaper models
   - `--quality` → prefers benchmark-ranked models
   - `--latency fast` → excludes cursor-subagent (unbounded queue)
   - `--output-heavy` → prefers high `max_output_k`
   - `--diversity` → picks one per vendor family
5. Optional `--companion auto|MODEL` → suggest a cheap cross-vendor companion
6. Print ranked list or JSON

### Hard-coded vs. flexible

| Hard-coded | Flexible |
|-----------|---------|
| `FALLBACKS` dict (e.g. `reviewer → [cursor-claude-4.7-opus]`) | All signals via flags |
| Actor detection commands | `ROUNDTABLE_CURSOR_AVAILABLE` env |
| 5s subprocess timeouts | N/A |

### Capability impact

`--latency fast` removes Cursor-only models (fine for async; bad if they're the best option).  
`--diversity` collapses to one per family — useful to force cross-vendor but loses ranked alternatives.

### Recommendation

Treat `route.sh` output as a **starting suggestion**, not a mandate. The agent should apply judgment on top of the ranking. Soften `FALLBACKS` to warn rather than hard-error when a role has no registered aliases.

---

## `backend.sh`

### What it does

- `init` — copies `models.example.json` → `models.json` if not present
- `show` — prints import status (keys redacted via `***`)
- `apply` — reads `active` + models from `models.json`, writes `.codex_env.local` / `.claude_env.local` with proper quoting (`printf %q`), `chmod 600`
- `codex` / `claude` subcommands — write individual actor env exports
- `help-import` — prints user-facing setup instructions
- `clear` — removes env files

### Security properties

- Never prints raw API keys (grep redaction in `show`)
- `chmod 600` on generated env files
- `printf %q` prevents injection via special chars in keys/URLs

### Essential: yes. Replacement by agent: no.

Secret handling must be deterministic and side-effect-free for review.

---

## `new_thread.sh`

Creates `threads/<slug>/` with subdirs (`artifacts/`, `history/`, `worktrees/`), seeds `THREAD.md`, `GOAL.md`, `OPEN_QUESTIONS.md` from templates, creates `latest` symlink.

Hard-coded: slug regex `^[a-z0-9][a-z0-9-]*$`. Flexible: root via `ROUNDTABLE_ROOT` env.

---

## `append_turn.sh`

Lands a Cursor subagent's five-part turn body into the thread. Steps:
1. Validate five-part turn body structure
2. Copy to `history/cursor/<ts>/last.md`
3. Append to `THREAD.md`
4. Extract verdict JSON for `reviewer`, `reviewer-aggregator`, and `devils-advocate`
5. Patch token count in `meta.json`
6. `emit_done`

---

## `compact_thread.sh` / `compact_thread.py` / `compact_recent_turns.py`

### What they do

`compact_thread.sh`: counts turns → if above `--keep`, calls `compact_thread.py` → merges old turns into `THREAD_SUMMARY.md`, replaces body of `THREAD.md`.

`compact_thread.py`: splits on `## Turn N` headers → tail K kept verbatim; older turns: extracts `**Summary**` + first 500 chars of `**Verification**`, strips `**Read**` entirely.

`compact_recent_turns.py`: called from `build_prompt`; returns last K turns with verification capped at `ROUNDTABLE_VERIFICATION_LIMIT` chars.

### Capability impact (important)

Compaction **loses evidence chains**. Old `**Read**` sections (raw file content, command output) are stripped entirely. A future agent turn that re-reads compacted context cannot trace how earlier agents reached their conclusions. This can cause:
- Re-derivation of the same facts (waste)
- Silent over-trust of summarized verdicts (contradicts Principle B)

**Recommendation:** Run compaction deliberately when a thread is complete or before archiving. Never auto-compact mid-active-thread.

---

## Python helpers summary

| Script | Purpose | Essential |
|--------|---------|-----------|
| `latest_verdict_block.py` | Inject pruned prior verdict; skip when blind | Yes |
| `salvage_codex_trace.py` | Recover output from JSONL on crash/timeout | Yes |
| `extract_claude_result.py` | Parse Claude JSON without requiring jq | Yes |
| `compact_thread.py` | Thread-level compaction logic | Yes (for compact) |
| `compact_recent_turns.py` | Prompt-level tail with truncation | Yes |
