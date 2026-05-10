---
name: roundtable-discuss
description: Deprecated — use roundtable-plan Phase A instead.
disable-model-invocation: true
---

# Roundtable Discuss (deprecated)

This sub-skill is **deprecated**. The workflow it described (cross-vendor option matrices without a final recommendation) now lives under **`skills/roundtable-plan/SKILL.md`** as **Phase A** (outputs merged into `artifacts/options.md`).

**Replacement:** Run `roundtable-plan` and set the parent/orchestrator checkpoint with:

`ROUNDTABLE_STOP_AFTER_PLAN_PHASE=phase-a`

That stops after the options matrix is ready so the user can review before Phase B produces `artifacts/PLAN.md`.

Do not route new work here — open `roundtable-plan` and follow Phase A / Phase B there.
