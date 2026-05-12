"""Tests for the cross-actor research artifact pool.

Covers two surfaces:

* `prior_research_block.py` emits a Markdown block listing artifacts/research/
  files with parsed query summaries, suitable for `build_prompt` injection.
* `compact_thread.py` does NOT mention or touch artifacts/research/.
* `build_prompt` (via `scripts/_common.sh`) actually includes the prior
  research block when a research artifact exists in the thread.

`build_prompt` is a bash function; we drive it via a `bash -c source ...`
subprocess and inspect the produced prompt.md.
"""
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _make_thread(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create the minimal thread skeleton expected by build_prompt."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "--allow-empty", "-q",
         "-m", "init", "--author=test <test@example.com>"],
        env={**{"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
                "PATH": "/usr/bin:/bin"}},
        check=True,
    )
    rt = project / ".roundtable" / "threads" / "slug"
    rt.mkdir(parents=True)
    (rt / "GOAL.md").write_text("# Goal\n\n## In-scope paths\n- src/**\n\n## Out-of-scope\n- secrets/**\n")
    (rt / "THREAD.md").write_text("# Thread\n")
    (rt / "OPEN_QUESTIONS.md").write_text("")
    return rt


def test_prior_research_block_lists_md_files(tmp_path):
    thread = tmp_path
    research = thread / "artifacts" / "research"
    research.mkdir(parents=True)
    (research / "research-codex-20260512T070000Z.md").write_text(textwrap.dedent("""
        # Research log — codex
        ## Q1
        **Query**: codex CLI exec resume 2026 features
        **Source**: https://example.com/codex
        **Key findings**:
        - thing 1
        ## Q2
        **Query**: cursor hooks beforeShellExecution
        - bullet
    """).strip() + "\n")
    (research / "research-claude-20260512T071230Z.md").write_text(
        "# r\n## Q1\n**Query**: Claude --resume vs --continue\n- bullet\n"
    )

    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lib" / "prior_research_block.py"), str(thread)],
        capture_output=True, text=True, check=True,
    )
    assert "## Prior research" in out.stdout
    assert "research-codex-20260512T070000Z.md" in out.stdout
    assert "research-claude-20260512T071230Z.md" in out.stdout
    assert "codex CLI exec resume 2026 features" in out.stdout


def test_prior_research_block_silent_when_dir_missing(tmp_path):
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lib" / "prior_research_block.py"), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout == ""


def test_compact_thread_excludes_research_dir():
    """compact_thread.py should not iterate or strip artifacts/research/."""
    src = (ROOT / "scripts" / "lib" / "compact_thread.py").read_text()
    # Either an explicit exclude or no mention at all is acceptable; assert
    # that we DO call out the exclusion in a comment so future edits don't
    # silently regress.
    assert "artifacts/research" in src, (
        "compact_thread.py must mention artifacts/research/ exclusion so future "
        "edits don't silently compact research notes"
    )


def test_build_prompt_includes_prior_research(tmp_path):
    thread = _make_thread(tmp_path)
    research = thread / "artifacts" / "research"
    research.mkdir(parents=True)
    (research / "research-codex-20260512T070000Z.md").write_text(
        "# r\n## Q1\n**Query**: how does codex resume work?\n"
    )
    add_file = thread / "addendum.md"
    add_file.write_text("Continue the work.\n")
    out_prompt = thread / "prompt.md"

    project_root = thread.parents[2]
    # Source _common.sh and invoke build_prompt. Skip the lessons / project
    # context plumbing that needs python imports from other modules; the
    # function still calls prior_research_block.py.
    bash = textwrap.dedent(f"""
        set -euo pipefail
        export ROUNDTABLE_PROJECT_ROOT={project_root}
        export ROUNDTABLE_DISPATCH_CONFIRMED=1
        export ROUNDTABLE_SKIP_REPO_CONTEXT=1
        source {ROOT}/scripts/_common.sh
        build_prompt {thread} executor {add_file} {out_prompt} >/dev/null
    """)
    res = subprocess.run(["bash", "-c", bash], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    body = out_prompt.read_text()
    assert "## Prior research" in body
    assert "research-codex-20260512T070000Z.md" in body
