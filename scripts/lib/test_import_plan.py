"""Tests for import_plan.py."""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from import_plan import main, update_goal_md  # noqa: E402


def test_update_goal_inserts_before_definition(tmp_path: pathlib.Path) -> None:
    goal = tmp_path / "GOAL.md"
    goal.write_text(
        "# Goal — t\n\n## One-line goal\nx\n\n## Definition of done\n- [ ] a\n",
        encoding="utf-8",
    )
    block = "## Plan source\n\nline1\n"
    update_goal_md(goal, block)
    text = goal.read_text(encoding="utf-8")
    assert "## Plan source" in text
    assert text.index("## Plan source") < text.index("## Definition of done")


def test_import_plan_end_to_end(tmp_path: pathlib.Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)

    slug = "test-thread"
    thread = tmp_path / ".roundtable" / "threads" / slug
    (thread / "artifacts").mkdir(parents=True)
    goal = thread / "GOAL.md"
    goal.write_text(
        "# Goal — test\n\n## One-line goal\ny\n\n## Definition of done\n- [ ]\n\n"
        "## In-scope paths (absolute)\n- src/\n",
        encoding="utf-8",
    )
    src = tmp_path / "cursor.plan.md"
    src.write_text("# My plan\n\nStep 1 do thing.\n", encoding="utf-8")

    assert main([slug, str(src), "--project", str(tmp_path), "--reviewed", "yes"]) == 0

    plan = thread / "artifacts" / "PLAN.md"
    assert plan.exists()
    body = plan.read_text(encoding="utf-8")
    assert "roundtable-import:" in body
    assert "Step 1 do thing" in body

    g = goal.read_text(encoding="utf-8")
    assert "**Cross-vendor review completed**: `yes`" in g
    assert str(src.resolve()) in g
