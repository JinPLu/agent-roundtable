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

1. Parse args (same structure + `--bare`, `--allowed-tools`, `--permission-mode`)
2. `resolve_model` (resolves first alias in `role_defaults[role]` whose `actor` matches `claude`)
3. Set `permission-mode` default by role:
   - reviewer / devils-advocate: `plan` (no edits)
   - others: `default`
4. Build tool allowlist by role:
   - reviewer: Read, Glob, Grep, specific Bash prefixes only
   - executor: Read + write tools, disallows dangerous git/network
5. Set `ROUNDTABLE_SKIP_ROLE_SYS=1` — role file passed as `--append-system-prompt` (not injected twice)
6. Run `timeout $TIMEOUT claude -p "$PROMPT" --append-system-prompt ROLE --output-format json ...`
7. Extract result via `extract_claude_result.py` (jq optional)
8. Append turn, extract verdict, meta + done

### Hard-coded

- Reviewer tool allowlist (Read, Glob, Grep, specific bash patterns)
- Executor disallows destructive git commands
- Default timeout 1500s

### Flexible

`--model`, `--bare` (reduces `CLAUDE.md` influence for isolation), `--blind`, `--timeout-s`, `--allowed-tools` override, `--permission-mode` override

### Capability impact

`--bare` skips `CLAUDE.md` — good for blind reviewers (isolation), but removes useful project context for executors. Consider only using `--bare` in review roles.

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
- `apply` — reads `active` + models from `models.json`, writes `.codex_env.local` / `.claude_env.local` with proper quoting (`printf %q`), `chmod 600`. **After writing env files, automatically calls `setup_tools.sh`** so the freshly-credentialed CLIs come up with their full tool surface.
- `tools` — standalone wrapper for `setup_tools.sh` (re-verify CLI tooling after a CLI upgrade or to debug a missing MCP server)
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

## `setup_tools.sh`

### What it does

Wires each agent CLI to its full diagnostic tool surface so the roundtable runs at "full capability" the moment install completes — no manual `codex mcp add` post-step.

1. Sources `OoVMetric/resource/proxy.txt` (or `$ROUNDTABLE_PROXY_FILE`) so PyPI is reachable from the corporate network; exports `UV_INDEX_URL=https://pypi.org/simple/` to bypass local mirrors that don't carry MCP packages.
2. **Codex CLI** — for each required MCP server (`ddg-search` via `uvx duckduckgo-mcp-server`, `fetch` via `uvx mcp-server-fetch`):
   - skips if `codex mcp get <name>` already returns a config (idempotent),
   - otherwise runs `codex mcp add <name> --env http_proxy=… --env UV_INDEX_URL=… -- uvx <pkg>`,
   - warms the `uvx` cache best-effort so the first request is fast.
3. **Claude Code** — verifies the binary is on `PATH` and `--allowed-tools` appears in `--help` (proxy for "native WebSearch / WebFetch / Bash / Read / Edit / Write / Grep / Glob are present"). No MCP step needed; per-role surface is enforced inside `claude_turn.sh`.
4. Prints a 3-bucket summary: newly installed / already configured / failed, plus `codex mcp list`. Exits non-zero only if a required tool failed to install.

### Hard-coded vs. flexible

| Hard-coded | Flexible |
|-----------|---------|
| MCP server names (`ddg-search`, `fetch`) and PyPI packages | Proxy file path via `ROUNDTABLE_PROXY_FILE` env |
| Public PyPI as the uv index | `UV_INDEX_URL` / `UV_DEFAULT_INDEX` env overrides |
| Idempotency check via `codex mcp get` | — |

### Triggering

- Auto-called at the end of `backend.sh apply`.
- Standalone via `backend.sh tools` or directly: `scripts/setup_tools.sh`.

### Essential: yes. Replacement by agent: no.

Tool wiring must be deterministic and observable; an LLM picking which MCP servers to install per session would be non-reproducible and would re-pay the install cost on every cold start.

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
