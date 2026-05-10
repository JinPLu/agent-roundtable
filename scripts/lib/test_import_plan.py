"""Tests for import_plan.py."""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from import_plan import (  # noqa: E402
    _derive_goal,
    _derive_slug,
    _parse_positionals,
    main,
    update_goal_md,
)


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


def test_derive_slug_from_plan_filename(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "oovmetric_cleanup_tidy_9a795f3b.plan.md"
    p.write_text("x")
    slug = _derive_slug(p)
    assert slug.startswith("oovmetric-cleanup-tidy-9a795f3b-")
    # ends with YYYYMMDD
    assert len(slug.rsplit("-", 1)[-1]) == 8


def test_derive_goal_from_yaml_overview(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "x.plan.md"
    p.write_text("---\nname: X\noverview: Clean up A and B.\n---\n# Heading\n", encoding="utf-8")
    assert _derive_goal(p) == "Clean up A and B."


def test_derive_goal_falls_back_to_h1(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "x.plan.md"
    p.write_text("# Implement feature X\n\nbody...\n", encoding="utf-8")
    assert _derive_goal(p) == "Implement feature X"


def test_parse_positionals_single_file(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "a.plan.md"
    f.write_text("x")
    slug, plan = _parse_positionals([str(f)])
    assert slug is None and plan == pathlib.Path(str(f))


def test_parse_positionals_legacy_two(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "a.plan.md"
    f.write_text("x")
    slug, plan = _parse_positionals(["my-slug", str(f)])
    assert slug == "my-slug" and plan == pathlib.Path(str(f))


def _init_git(tmp_path: pathlib.Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)


def test_import_plan_end_to_end_legacy(tmp_path: pathlib.Path) -> None:
    _init_git(tmp_path)
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


def test_import_plan_auto_creates_thread(tmp_path: pathlib.Path) -> None:
    _init_git(tmp_path)
    src = tmp_path / "auto_plan_demo.plan.md"
    src.write_text("---\noverview: Auto demo overview.\n---\n# Heading\n", encoding="utf-8")

    rc = main([str(src), "--project", str(tmp_path)])
    assert rc == 0

    threads_dir = tmp_path / ".roundtable" / "threads"
    created = [p for p in threads_dir.iterdir() if p.is_dir() and p.name != "latest"]
    assert len(created) == 1
    thread = created[0]
    assert thread.name.startswith("auto-plan-demo-")
    assert (thread / "GOAL.md").is_file()
    plan = thread / "artifacts" / "PLAN.md"
    assert plan.is_file()
    assert "Auto demo overview" in (thread / "GOAL.md").read_text() or "Auto demo overview" in plan.read_text()


def test_reimport_existing_thread(tmp_path: pathlib.Path) -> None:
    _init_git(tmp_path)
    src = tmp_path / "x.plan.md"
    src.write_text("# A\nbody1\n", encoding="utf-8")

    assert main([str(src), "--project", str(tmp_path), "--slug", "fixed-slug-20260511"]) == 0
    # edit and re-import to the same slug
    src.write_text("# A\nbody2\n", encoding="utf-8")
    assert main([str(src), "--project", str(tmp_path), "--slug", "fixed-slug-20260511", "--reviewed", "yes"]) == 0

    plan = tmp_path / ".roundtable" / "threads" / "fixed-slug-20260511" / "artifacts" / "PLAN.md"
    assert "body2" in plan.read_text(encoding="utf-8")
    g = (tmp_path / ".roundtable" / "threads" / "fixed-slug-20260511" / "GOAL.md").read_text()
    assert "`yes`" in g
