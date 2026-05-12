"""Unit tests for ``install_hooks`` — fresh / preserve / idempotent / uninstall.

Run from the repo root with: ``python3 -m pytest scripts/lib/test_install_hooks.py``.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

# Allow ``import install_hooks`` even when pytest is invoked from repo root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import install_hooks  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fake_skill(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a minimal skill tree (templates/hooks.json.tmpl + executable
    hook scripts) so the smoketest passes."""
    skill = tmp_path / "skill"
    (skill / "hooks").mkdir(parents=True)
    (skill / "templates").mkdir(parents=True)

    for name in (
        "roundtable-dispatch-gate.sh",
        "roundtable-diversity-block.sh",
        "roundtable-oracle-post.sh",
        "roundtable-budget-gate.sh",
        "roundtable-autopilot-continue.sh",
    ):
        p = skill / "hooks" / name
        p.write_text("#!/usr/bin/env bash\necho '{}'\n")
        p.chmod(0o755)

    template = {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [
                {"_roundtable_id": "roundtable.h1.dispatch-gate",
                 "command": "<SKILL_DIR>/hooks/roundtable-dispatch-gate.sh"},
                {"_roundtable_id": "roundtable.h2.diversity-block",
                 "command": "<SKILL_DIR>/hooks/roundtable-diversity-block.sh"},
                {"_roundtable_id": "roundtable.h4.budget-gate",
                 "command": "<SKILL_DIR>/hooks/roundtable-budget-gate.sh"},
            ],
            "postToolUse": [
                {"_roundtable_id": "roundtable.h3.oracle-post",
                 "command": "<SKILL_DIR>/hooks/roundtable-oracle-post.sh",
                 "matcher": "Shell"},
            ],
            "stop": [
                {"_roundtable_id": "roundtable.h5.autopilot-continue",
                 "command": "<SKILL_DIR>/hooks/roundtable-autopilot-continue.sh",
                 "loop_limit": 15},
            ],
        },
    }
    (skill / "templates" / "hooks.json.tmpl").write_text(
        json.dumps(template, indent=2) + "\n"
    )
    return skill


def _run(skill: pathlib.Path, target: pathlib.Path, *extra: str) -> int:
    argv = [
        "--skill-dir", str(skill),
        "--template", str(skill / "templates" / "hooks.json.tmpl"),
        "--target", str(target),
        *extra,
    ]
    return install_hooks.run(argv)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_fresh_install(tmp_path, fake_skill):
    """Installing into a path with no pre-existing hooks.json creates the
    file with all five roundtable entries and a backup is not made
    (nothing to back up)."""
    target = tmp_path / "hooks.json"
    rc = _run(fake_skill, target)
    assert rc == 0
    data = json.loads(target.read_text())
    assert data["version"] == 1
    ids = sorted(install_hooks._entry_ids(data))
    assert ids == [
        "roundtable.h1.dispatch-gate",
        "roundtable.h2.diversity-block",
        "roundtable.h3.oracle-post",
        "roundtable.h4.budget-gate",
        "roundtable.h5.autopilot-continue",
    ]
    # SKILL_DIR placeholder must have been expanded to an absolute path.
    cmds = [
        e["command"]
        for entries in data["hooks"].values()
        for e in entries
    ]
    assert all("<SKILL_DIR>" not in c for c in cmds), cmds
    assert all(c.startswith(str(fake_skill)) for c in cmds), cmds
    bak = target.with_suffix(target.suffix + ".roundtable-bak")
    assert not bak.exists()  # nothing to back up on a fresh install


def test_preserve_existing_user_hooks(tmp_path, fake_skill):
    """Pre-existing user hooks (without _roundtable_id) must survive
    intact after our install."""
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "beforeShellExecution": [
                {"command": "/usr/local/bin/my-personal-guardrail.sh"}
            ],
            "afterFileEdit": [
                {"command": "/usr/local/bin/audit.sh"}
            ],
        },
    }))
    rc = _run(fake_skill, target)
    assert rc == 0
    data = json.loads(target.read_text())
    # User's afterFileEdit hook untouched.
    assert data["hooks"]["afterFileEdit"] == [
        {"command": "/usr/local/bin/audit.sh"}
    ]
    # User's beforeShellExecution hook untouched, plus 3 roundtable ones.
    pre = data["hooks"]["beforeShellExecution"]
    user_entries = [e for e in pre if not install_hooks.is_roundtable_entry(e)]
    rt_entries = [e for e in pre if install_hooks.is_roundtable_entry(e)]
    assert user_entries == [{"command": "/usr/local/bin/my-personal-guardrail.sh"}]
    assert len(rt_entries) == 3
    # Backup was made.
    bak = target.with_suffix(target.suffix + ".roundtable-bak")
    assert bak.exists()


def test_idempotent_reinstall(tmp_path, fake_skill):
    """A second install over a freshly-installed file must produce no
    further changes (same JSON bytes, no duplicate entries)."""
    target = tmp_path / "hooks.json"
    assert _run(fake_skill, target) == 0
    first_bytes = target.read_text()
    assert _run(fake_skill, target) == 0
    second_bytes = target.read_text()
    assert first_bytes == second_bytes
    data = json.loads(second_bytes)
    # Exactly one of each roundtable id.
    ids = [
        e["_roundtable_id"]
        for entries in data["hooks"].values()
        for e in entries
        if install_hooks.is_roundtable_entry(e)
    ]
    assert sorted(ids) == sorted(set(ids))
    assert len(ids) == 5


def test_uninstall_removes_only_roundtable_entries(tmp_path, fake_skill):
    """After install + uninstall the target must be back to the user's
    original content (modulo a backup file)."""
    target = tmp_path / "hooks.json"
    user_content = {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [
                {"command": "/usr/local/bin/my-personal-guardrail.sh"}
            ],
        },
    }
    target.write_text(json.dumps(user_content))
    assert _run(fake_skill, target) == 0
    assert _run(fake_skill, target, "--uninstall") == 0
    data = json.loads(target.read_text())
    assert data["hooks"]["beforeShellExecution"] == [
        {"command": "/usr/local/bin/my-personal-guardrail.sh"}
    ]
    # No roundtable entries remain.
    for entries in data["hooks"].values():
        for e in entries:
            assert not install_hooks.is_roundtable_entry(e)


def test_dry_run_does_not_write(tmp_path, fake_skill):
    target = tmp_path / "hooks.json"
    rc = _run(fake_skill, target, "--dry-run")
    assert rc == 0
    assert not target.exists()


def test_smoketest_catches_missing_hook(tmp_path, fake_skill):
    """If a hook script disappears between checkout and install we abort
    before clobbering the target file."""
    (fake_skill / "hooks" / "roundtable-dispatch-gate.sh").unlink()
    target = tmp_path / "hooks.json"
    rc = _run(fake_skill, target)
    assert rc == 3
    assert not target.exists()


def test_uninstall_when_target_missing(tmp_path, fake_skill):
    """Uninstalling against a nonexistent target is a no-op, not an error."""
    target = tmp_path / "absent.json"
    rc = _run(fake_skill, target, "--uninstall")
    assert rc == 0
    assert not target.exists()


def test_uninstall_drops_empty_event_keys(tmp_path, fake_skill):
    """After uninstall, any event whose only entries were ours collapses
    away — keep the file tidy."""
    target = tmp_path / "hooks.json"
    assert _run(fake_skill, target) == 0  # install
    assert _run(fake_skill, target, "--uninstall") == 0
    data = json.loads(target.read_text())
    # `stop` and `postToolUse` had only roundtable entries; they should be
    # gone now.
    assert "stop" not in data.get("hooks", {})
    assert "postToolUse" not in data.get("hooks", {})


def test_replace_outdated_roundtable_entry(tmp_path, fake_skill):
    """If a roundtable entry already exists with a stale path, install
    must replace it (not append a duplicate)."""
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "stop": [
                {"_roundtable_id": "roundtable.h5.autopilot-continue",
                 "command": "/old/wrong/path/h5.sh",
                 "loop_limit": 1},
            ],
        },
    }))
    assert _run(fake_skill, target) == 0
    data = json.loads(target.read_text())
    stop = data["hooks"]["stop"]
    assert len(stop) == 1
    assert "/old/wrong/path" not in stop[0]["command"]
    assert stop[0]["loop_limit"] == 15
