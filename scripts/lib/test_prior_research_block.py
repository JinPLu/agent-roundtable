"""Tests for prior_research_block."""

from __future__ import annotations

import pathlib
import subprocess
import sys


def test_prior_research_lists_queries(tmp_path: pathlib.Path) -> None:
    rd = tmp_path / "artifacts" / "research"
    rd.mkdir(parents=True)
    (rd / "research-codex-20260101.md").write_text(
        "## Q1\n**Query**: hello world\n**Source**: https://ex.example\n",
        encoding="utf-8",
    )
    script = pathlib.Path(__file__).resolve().parent / "prior_research_block.py"
    out = subprocess.check_output([sys.executable, str(script), str(tmp_path)], text=True)
    assert "Prior research" in out
    assert "hello world" in out
