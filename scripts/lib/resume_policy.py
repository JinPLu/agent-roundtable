#!/usr/bin/env python3
"""Role-aware resume policy for Codex / Claude roundtable turns."""
from __future__ import annotations


def resume_allowed_for_role(
    role: str,
    *,
    blind: bool,
    planner_mode: str,
    force_resume: bool,
    no_resume: bool,
) -> tuple[bool, str]:
    """Return (allowed, reason_code).

    reviewer*, devils-advocate: never resume (blind integrity).
    blind flag: never resume.
    planner fresh fan-out: no resume; planner refine: resume OK.
    """
    if no_resume and not force_resume:
        return False, "no_resume_flag"
    if blind:
        return False, "blind_turn"
    if role in ("reviewer", "reviewer-aggregator", "devils-advocate"):
        return False, "review_role_hard_no"
    if role == "planner" and planner_mode == "fresh":
        return False, "planner_fresh_fanout"
    if role in (
        "executor",
        "executor-fast",
        "executor-heavy",
        "researcher",
        "researcher-deep",
        "discussant",
        "planner",
    ):
        return True, "role_default_yes"
    # conservative default for unknown roles
    return False, "unknown_role"


def marker_still_valid(
    *,
    marker_age_s: float,
    ttl_s: float,
    marker_model: str,
    current_model: str,
    marker_git_sha: str | None,
    current_git_sha: str | None,
    autopilot_continue: bool,
    force_resume: bool,
) -> tuple[bool, str]:
    if force_resume:
        return True, "force_resume"
    if marker_model != current_model:
        return False, "model_changed"
    if (
        marker_git_sha
        and current_git_sha
        and marker_git_sha != current_git_sha
        and not autopilot_continue
    ):
        return False, "git_head_changed"
    if marker_age_s > ttl_s and not autopilot_continue:
        return False, "ttl_expired"
    return True, "ok"
