"""Tests for the role-aware resume policy (scripts/lib/_resume.sh).

We exercise the bash helper by sourcing it in a subshell and asserting on
exit codes — same contract the turn scripts rely on. Also smoke-tests the
companion Python module `resume_policy.py` (the bash helper delegates the
TTL/git_sha check to Python anyway, so its semantics need to match).
"""
import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESUME_SH = ROOT / "scripts" / "lib" / "_resume.sh"

sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import resume_policy as rp  # noqa: E402


def _make_marker(path: pathlib.Path, *, sid: str = "abc123", age_s: int = 0,
                 model: str = "gpt-5", git_sha: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": sid,
        "ts": int(time.time() - age_s),
        "model": model,
        "git_sha": git_sha,
    }
    path.write_text(json.dumps(payload))


def _run_should_resume(role: str, marker: pathlib.Path, blind: str = "0",
                       model: str = "gpt-5", env_overrides: dict | None = None,
                       project_root: str = "") -> int:
    env = {**os.environ, "ROUNDTABLE_PROJECT_ROOT": project_root}
    if env_overrides:
        env.update(env_overrides)
    script = (
        f"source {RESUME_SH}; "
        f"if _should_resume {role} {marker} {blind} {model}; then exit 0; else exit 1; fi"
    )
    return subprocess.run(["bash", "-c", script], env=env).returncode


# ── bash _should_resume ──────────────────────────────────────────────────────


def test_blind_always_denies(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    rc = _run_should_resume("executor", marker, blind="1")
    assert rc == 1


def test_reviewer_role_hard_no(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    for role in ("reviewer", "reviewer-aggregator", "devils-advocate"):
        rc = _run_should_resume(role, marker)
        assert rc == 1, role


def test_executor_with_valid_marker_resumes(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    rc = _run_should_resume("executor", marker)
    assert rc == 0


def test_missing_marker_denies(tmp_path):
    rc = _run_should_resume("executor", tmp_path / "missing.json")
    assert rc == 1


def test_no_resume_env_denies(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    rc = _run_should_resume("executor", marker, env_overrides={"ROUNDTABLE_NO_RESUME": "1"})
    assert rc == 1


def test_planner_fresh_denies(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    rc = _run_should_resume("planner", marker)
    # default fresh
    assert rc == 1


def test_planner_refine_allows(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker)
    rc = _run_should_resume(
        "planner", marker,
        env_overrides={"ROUNDTABLE_PLANNER_MODE": "refine"},
    )
    assert rc == 0


def test_ttl_expired_denies(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker, age_s=25 * 3600)
    rc = _run_should_resume("executor", marker)
    assert rc == 1


def test_autopilot_bypasses_ttl(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker, age_s=25 * 3600)
    rc = _run_should_resume(
        "executor", marker,
        env_overrides={"ROUNDTABLE_AUTOPILOT_CONTINUE": "1"},
    )
    assert rc == 0


def test_model_mismatch_denies(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker, model="gpt-5")
    rc = _run_should_resume("executor", marker, model="gpt-5-mini")
    assert rc == 1


def test_force_resume_bypasses_ttl_but_requires_model_match(tmp_path):
    marker = tmp_path / "m.json"
    _make_marker(marker, age_s=25 * 3600, model="gpt-5")
    rc = _run_should_resume(
        "executor", marker, model="gpt-5",
        env_overrides={"ROUNDTABLE_FORCE_RESUME": "1"},
    )
    assert rc == 0
    rc2 = _run_should_resume(
        "executor", marker, model="gpt-5-mini",
        env_overrides={"ROUNDTABLE_FORCE_RESUME": "1"},
    )
    assert rc2 == 1


def test_git_sha_change_denies_outside_autopilot(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-q", "--allow-empty", "-m", "x",
                    "--author=t <t@x>"],
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"},
                   check=True)
    marker = tmp_path / "m.json"
    _make_marker(marker, git_sha="0" * 40)
    rc = _run_should_resume(
        "executor", marker,
        env_overrides={"ROUNDTABLE_PROJECT_ROOT": str(project)},
        project_root=str(project),
    )
    assert rc == 1


# ── _marker_persist_eligible ───────────────────────────────────────────────


def _eligible(role: str, blind: str = "0") -> int:
    script = (
        f"source {RESUME_SH}; "
        f"if _marker_persist_eligible {role} {blind}; then exit 0; else exit 1; fi"
    )
    return subprocess.run(["bash", "-c", script]).returncode


def test_persist_eligible_executor():
    assert _eligible("executor") == 0


def test_persist_eligible_blind_denied():
    assert _eligible("executor", blind="1") == 1


def test_persist_eligible_reviewer_denied():
    for role in ("reviewer", "reviewer-aggregator", "devils-advocate"):
        assert _eligible(role) == 1, role


# ── companion Python module ─────────────────────────────────────────────────


def test_resume_policy_module_blind():
    allowed, reason = rp.resume_allowed_for_role(
        "executor", blind=True, planner_mode="fresh",
        force_resume=False, no_resume=False,
    )
    assert allowed is False
    assert reason == "blind_turn"


def test_resume_policy_module_reviewer():
    allowed, reason = rp.resume_allowed_for_role(
        "reviewer", blind=False, planner_mode="fresh",
        force_resume=False, no_resume=False,
    )
    assert allowed is False
    assert reason == "review_role_hard_no"


def test_resume_policy_module_planner_modes():
    allowed_fresh, _ = rp.resume_allowed_for_role(
        "planner", blind=False, planner_mode="fresh",
        force_resume=False, no_resume=False,
    )
    allowed_refine, _ = rp.resume_allowed_for_role(
        "planner", blind=False, planner_mode="refine",
        force_resume=False, no_resume=False,
    )
    assert allowed_fresh is False
    assert allowed_refine is True


def test_resume_policy_module_no_resume_overrides_force_false():
    allowed, _ = rp.resume_allowed_for_role(
        "executor", blind=False, planner_mode="fresh",
        force_resume=False, no_resume=True,
    )
    assert allowed is False


def test_marker_still_valid_ttl():
    ok, _ = rp.marker_still_valid(
        marker_age_s=1.0, ttl_s=86400.0,
        marker_model="m", current_model="m",
        marker_git_sha="abc", current_git_sha="abc",
        autopilot_continue=False, force_resume=False,
    )
    assert ok is True
    bad, reason = rp.marker_still_valid(
        marker_age_s=86401.0, ttl_s=86400.0,
        marker_model="m", current_model="m",
        marker_git_sha=None, current_git_sha=None,
        autopilot_continue=False, force_resume=False,
    )
    assert bad is False
    assert reason == "ttl_expired"


def test_marker_still_valid_autopilot_bypasses_ttl():
    ok, _ = rp.marker_still_valid(
        marker_age_s=86401.0, ttl_s=86400.0,
        marker_model="m", current_model="m",
        marker_git_sha=None, current_git_sha=None,
        autopilot_continue=True, force_resume=False,
    )
    assert ok is True


def test_marker_still_valid_git_sha_mismatch_outside_autopilot():
    bad, reason = rp.marker_still_valid(
        marker_age_s=1.0, ttl_s=86400.0,
        marker_model="m", current_model="m",
        marker_git_sha="aaa", current_git_sha="bbb",
        autopilot_continue=False, force_resume=False,
    )
    assert bad is False
    assert reason == "git_head_changed"
