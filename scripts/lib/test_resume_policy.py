"""Tests for resume_policy."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import resume_policy as rp  # noqa: E402


def test_reviewer_never_resume() -> None:
    ok, reason = rp.resume_allowed_for_role(
        "reviewer", blind=False, planner_mode="fresh", force_resume=False, no_resume=False
    )
    assert ok is False
    ok2, _ = rp.resume_allowed_for_role(
        "executor", blind=False, planner_mode="fresh", force_resume=False, no_resume=False
    )
    assert ok2 is True


def test_blind_blocks() -> None:
    ok, _ = rp.resume_allowed_for_role(
        "executor", blind=True, planner_mode="fresh", force_resume=False, no_resume=False
    )
    assert ok is False


def test_planner_fresh_vs_refine() -> None:
    ok_fresh, _ = rp.resume_allowed_for_role(
        "planner", blind=False, planner_mode="fresh", force_resume=False, no_resume=False
    )
    assert ok_fresh is False
    ok_refine, _ = rp.resume_allowed_for_role(
        "planner", blind=False, planner_mode="refine", force_resume=False, no_resume=False
    )
    assert ok_refine is True


def test_marker_ttl_and_autopilot() -> None:
    ok, _ = rp.marker_still_valid(
        marker_age_s=90000,
        ttl_s=86400,
        marker_model="gpt-5",
        current_model="gpt-5",
        marker_git_sha="abc",
        current_git_sha="abc",
        autopilot_continue=True,
        force_resume=False,
    )
    assert ok is True


def test_git_sha_invalidates() -> None:
    ok, reason = rp.marker_still_valid(
        marker_age_s=10,
        ttl_s=86400,
        marker_model="x",
        current_model="x",
        marker_git_sha="aaa",
        current_git_sha="bbb",
        autopilot_continue=False,
        force_resume=False,
    )
    assert ok is False
    assert reason == "git_head_changed"
