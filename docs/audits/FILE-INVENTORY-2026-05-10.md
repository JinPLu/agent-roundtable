# File Inventory

> Audit of every file in the `agent-roundtable` skill.  
> Generated: 2026-05-10

## Legend

- **Necessary?** — Essential / Nice-to-have / Redundant
- **Model-capability impact** — how the file constrains or enhances LLM reasoning/action
- **Recommendation** — Keep / Simplify / Fix / Remove

---

## Top-level files

| File | Role | Necessary? | Model-capability impact | Recommendation |
|------|------|------------|-------------------------|----------------|
| `SKILL.md` | Cursor skill spec: protocol, hard rules, dispatch UX, script index | Essential | **Constrains:** mandatory five-part turn body, blind review rules, user dispatch confirmation, `disable-model-invocation: true`. **Enhances:** anti-sycophancy guidance, clear audit trail | Keep |
| `README.md` | Short human-readable install guide | Nice-to-have | Neutral | Keep |
| `LICENSE` | MIT license | Essential for distribution | Neutral | Keep |
| `.gitignore` | Ignores secrets, `.roundtable/`, env files | Essential | Neutral — prevents key leakage | Keep |
| `models.example.json` | Shipped catalog + BYOK templates + `role_defaults` | Essential | **Constrains:** default ordering, example `cli_arg` strings. **Risk:** stale pricing snapshots can mislead routing decisions | Keep; refresh pricing `_as_of` dates periodically |
| `models.json` | User registry (workspace copy, gitignored) | Essential locally; **must not ship with secrets** | Defines which CLIs talk to which endpoints; wrong entries → wrong model routed | Keep locally only; rotate keys if ever committed |

---

## `scripts/`

| File | Role | Necessary? | Model-capability impact | Recommendation |
|------|------|------------|-------------------------|----------------|
| `_common.sh` | Repo root detection, `build_prompt`, `resolve_model`, `emit_done`, meta helpers | Essential | **Constrains:** prompt structure injection, tail truncation, blind verdict omission | Keep |
| `codex_turn.sh` | One Codex CLI turn: prompt → exec → salvage → append thread | Essential | Timeout 1800s, sandbox `workspace-write`, `approval_policy=never`; `--blind` supported | Keep |
| `claude_turn.sh` | One Claude CLI turn: prompt → exec → extract → append thread | Essential | Timeout 1500s, tool allowlists by role, `permission-mode plan` for reviewers, `--bare` supported | Keep; tune tool defaults per team needs |
| `route.sh` | Thin wrapper around `route.py`; prints ranked model suggestions | Essential | Steers parent toward specific aliases; `--latency fast` removes Cursor-only models | Keep |
| `backend.sh` | Init/apply/show/clear BYOK env for codex & claude actors | Essential | No impact on model reasoning; secures key handling | Keep |
| `new_thread.sh` | Creates thread directory layout + `latest` symlink | Essential | Neutral | Keep |
| `append_turn.sh` | Lands Cursor subagent output into thread | Essential for cursor-subagent actor | Same five-part turn body expectation; extracts verdict JSON for reviewer / reviewer-aggregator / devils-advocate | Keep |
| `compact_thread.sh` | Moves old turns to a summary block | Nice-to-have | Compaction is lossy — old Read/Verification chains lost for future reasoning | Keep; run deliberately, not automatically |

---

## `scripts/lib/`

| File | Role | Necessary? | Model-capability impact | Recommendation |
|------|------|------------|-------------------------|----------------|
| `route.py` | Rank models by role + signals (cost, quality, latency, diversity) | Essential | When `role_defaults[role]` is empty/missing, emits a stderr warning and exits empty (no hardcoded private aliases); `--diversity` collapses to one per vendor family | Keep |
| `compact_thread.py` | Mechanical compaction: strips Read sections, truncates Verification | Essential for compact script | Strips evidence chains — can hurt long reasoning context | Keep |
| `compact_recent_turns.py` | Token-focused tail of recent turns; optional read compaction | Essential | Verification truncated to ~1000 chars in injected prompts | Keep |
| `latest_verdict_block.py` | Injects pruned prior verdict into next prompt | Essential | **Blind turns skip entirely** — correctly enhances reviewer independence | Keep |
| `salvage_codex_trace.py` | Recover Codex output from JSONL trace on timeout/crash | Essential | Prevents silent empty `last.md` after timeouts | Keep |
| `extract_claude_result.py` | Parse Claude JSON result without requiring `jq` | Essential | Neutral | Keep |

---

## `roles/`

| File | Role | Necessary? | Model-capability impact | Recommendation |
|------|------|------------|-------------------------|----------------|
| `planner.system.md` | Planner system prompt | Essential | Mandates five-part-only final message; strong scope constraints | Keep |
| `executor.system.md` | Executor system prompt | Essential | Strong "verify everything before claiming done" | Keep |
| `reviewer.system.md` | Reviewer + aggregator instructions | Essential | Heavy structure; JSON-first Verification required; aggregator selects not blends | Keep; consider splitting aggregator into its own file |
| `devils-advocate.system.md` | Adversarial reviewer: find flaws, anti-sycophancy | Essential | Same JSON schema as reviewer; prose explicitly forbids the non-existent `pass` field | Keep |
| `discussant.system.md` | Discussion / option surfacing | Essential | Lighter than reviewer; no JSON schema constraint | Keep |
| `reviewer.schema.json` | Strict JSON verdict schema (`additionalProperties: false`) | Essential | Constrains model output format; extra keys fail downstream extraction | Keep |

---

## `templates/`

| File | Role | Necessary? | Model-capability impact | Recommendation |
|------|------|------------|-------------------------|----------------|
| `THREAD.tmpl` | Seed THREAD.md on new thread | Essential | Neutral | Keep |
| `GOAL.tmpl` | Seed GOAL.md on new thread | Essential | Neutral | Keep |
| `OPEN_QUESTIONS.tmpl` | Seed OPEN_QUESTIONS.md | Essential | Neutral | Keep |

---

## Generated / local files (not shipped)

| File | Role | Necessary? | Notes |
|------|------|------------|-------|
| `.codex_env.local` | Codex API key + base URL exports | Essential locally | Must be gitignored (`chmod 600`) |
| `.claude_env.local` | Claude API key + base URL exports | Essential locally | Must be gitignored (`chmod 600`) |
| `.git/` under skill dir | VCS metadata for skill repo | Redundant for consumers | Document or remove from distributed copies |

