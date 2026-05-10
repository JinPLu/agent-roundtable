"""Tests for scope_check.py."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import textwrap

import pytest

# Make sure the lib directory is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from scope_check import _parse_goal_md, _matches_any, main  # noqa: E402


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

def _write_goal(tmp_path: pathlib.Path, in_scope: list[str], out_scope: list[str]) -> pathlib.Path:
    lines = ["# Goal — test\n\n## One-line goal\ntest\n"]
    lines.append("\n## In-scope paths (absolute)\n")
    for p in in_scope:
        lines.append(f"- {p}\n")
    lines.append("\n## Out-of-scope / do-not-touch\n")
    for p in out_scope:
        lines.append(f"- {p}\n")
    goal = tmp_path / "GOAL.md"
    goal.write_text("".join(lines), encoding="utf-8")
    return goal


def test_parse_goal_md_basic(tmp_path: pathlib.Path) -> None:
    goal = _write_goal(tmp_path, ["src/", "tests/"], ["secrets/"])
    in_s, out_s = _parse_goal_md(goal)
    assert "src/" in in_s
    assert "tests/" in in_s
    assert "secrets/" in out_s


def test_parse_goal_md_missing(tmp_path: pathlib.Path) -> None:
    in_s, out_s = _parse_goal_md(tmp_path / "GOAL.md")
    assert in_s == []
    assert out_s == []


def test_matches_any_prefix() -> None:
    assert _matches_any("src/foo/bar.py", ["src/"])
    assert not _matches_any("docs/readme.md", ["src/"])


def test_matches_any_glob() -> None:
    assert _matches_any("src/foo.test.ts", ["src/*.test.ts"])
    assert not _matches_any("lib/foo.test.ts", ["src/*.test.ts"])


# ---------------------------------------------------------------------------
# Integration tests via CLI entry point
# ---------------------------------------------------------------------------

def _make_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"],
                   check=True, capture_output=True)
    init = tmp_path / "README.md"
    init.write_text("init\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
    return tmp_path


def _get_head(repo: pathlib.Path) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _make_thread(repo: pathlib.Path, slug: str, in_scope: list[str], out_scope: list[str]) -> pathlib.Path:
    thread_dir = repo / ".roundtable" / "threads" / slug
    thread_dir.mkdir(parents=True)
    _write_goal(thread_dir, in_scope, out_scope)
    return thread_dir


def _add_commit(repo: pathlib.Path, rel_path: str, content: str = "x\n") -> None:
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", rel_path], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", f"add {rel_path}"],
                   check=True, capture_output=True)


class TestScopeCheckCLI:
    def test_pass(self, tmp_path: pathlib.Path) -> None:
        repo = _make_git_repo(tmp_path)
        base = _get_head(repo)
        _make_thread(repo, "t1", ["src/"], [])
        _add_commit(repo, "src/app.py")

        ret = main(["--thread", "t1", "--base", base, "--project", str(repo)])
        assert ret == 0

    def test_violation(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        repo = _make_git_repo(tmp_path)
        base = _get_head(repo)
        _make_thread(repo, "t2", ["src/"], ["secrets/"])
        _add_commit(repo, "src/app.py")
        _add_commit(repo, "secrets/key.pem")

        ret = main(["--thread", "t2", "--base", base, "--project", str(repo)])
        assert ret == 1
        out = capsys.readouterr().out
        assert out.startswith("VIOLATION")
        assert "secrets/key.pem" in out

    def test_no_goal(self, tmp_path: pathlib.Path) -> None:
        repo = _make_git_repo(tmp_path)
        base = _get_head(repo)
        # Thread exists but GOAL.md has no In-scope section
        thread_dir = repo / ".roundtable" / "threads" / "t3"
        thread_dir.mkdir(parents=True)
        (thread_dir / "GOAL.md").write_text("# Goal\n\n## One-line goal\nfoo\n")
        _add_commit(repo, "src/app.py")

        ret = main(["--thread", "t3", "--base", base, "--project", str(repo)])
        assert ret == 2
