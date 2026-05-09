---
name: roundtable-init
description: Initialize agent-roundtable configuration, set up API keys, and generate project context files (AGENTS.md and CLAUDE.md). Use when the user asks to setup, initialize, or configure agent-roundtable.
---

# Roundtable Init

This skill encapsulates the setup and initialization workflow for `agent-roundtable`.

## Workflow

1. **Initialize Backend**:
   - Run `bash ~/.cursor/skills/agent-roundtable/scripts/backend.sh init`.
   - Tell the user to open `~/.cursor/skills/agent-roundtable/models.json` and fill in their `base_url` and `api_key` for the models they want to use.
   - Wait for the user to say "done" or "applied".

2. **Apply Configuration**:
   - Run `bash ~/.cursor/skills/agent-roundtable/scripts/backend.sh apply`.
   - Run `bash ~/.cursor/skills/agent-roundtable/scripts/backend.sh show` to verify the import status.

3. **Generate Project Context (Crucial for Full-Blood Agents)**:
   - If the project does not have `AGENTS.md` and `CLAUDE.md`, offer to generate them.
   - To generate:
     - Read the project structure, `README.md`, and any `.planning/` files.
     - Create `AGENTS.md` containing cross-platform rules (build commands, directory structure, PR rules).
     - Create `CLAUDE.md` containing exactly:
       ```markdown
       @AGENTS.md
       
       ## Claude Code Specifics
       - Default to `plan` mode for review tasks.
       ```
   - Explain to the user that these files ensure the agent CLI boots up with full project awareness.