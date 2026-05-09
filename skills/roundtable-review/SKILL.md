---
name: roundtable-review
description: Review code for quality, security, and logic using parallel blind agents from different vendors. Use when the user asks to review code, check a PR, or find bugs using agent-roundtable.
---

# Roundtable Review

This skill encapsulates the "Parallel Blind Review" mode of `agent-roundtable`.

## Workflow

When the user asks for a review:

1. **Do not ask for configuration details** unless `models.json` is missing. Assume the environment is ready.
2. **Determine the target**: Identify the files or PR the user wants reviewed.
3. **Dispatch Parallel Reviewers**:
   - Use the `Task` tool (or `Bash` if running CLI directly) to dispatch at least TWO reviewers from different vendors (e.g., one `codex` and one `claude`).
   - **CRITICAL**: You MUST pass the `--blind` flag to both reviewers so they don't see each other's verdicts.
   - Example CLI:
     ```bash
     $SKILL/scripts/codex_turn.sh <slug> --role reviewer --blind --task "Review <file>"
     $SKILL/scripts/claude_turn.sh <slug> --role devils-advocate --blind --task "Review <file>"
     ```
4. **Dispatch Aggregator**:
   - After the parallel reviewers finish, dispatch a `reviewer-aggregator` to select the best verdict.
   - Example CLI:
     ```bash
     $SKILL/scripts/claude_turn.sh <slug> --role reviewer-aggregator --task "Select the most defensible verdict"
     ```
5. **Report to User**:
   - Read the final aggregated verdict from the thread or `history/` and present the findings to the user.

## Rules
- Always use the mandatory dispatch confirmation block before running the scripts, unless the user explicitly said "go" or "dispatch now".
- Ensure `ROUNDTABLE_PROJECT_ROOT` is set correctly.