"""Tests for scripts/lib/install_codex_profile.py."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import install_codex_profile as icp  # noqa: E402


SNIPPET = """\
[profiles.roundtable-executor]
sandbox_mode = "workspace-write"
approval_policy = "never"

[profiles.roundtable-reviewer]
sandbox_mode = "read-only"
approval_policy = "never"
"""


def test_merge_into_empty_config(tmp_path):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    icp.cmd_apply(snippet, cfg, dry_run=False)
    text = cfg.read_text()
    assert "# roundtable-managed begin" in text
    assert "# roundtable-managed end" in text
    assert "[profiles.roundtable-executor]" in text


def test_idempotent_apply(tmp_path):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    icp.cmd_apply(snippet, cfg, dry_run=False)
    icp.cmd_apply(snippet, cfg, dry_run=False)
    text = cfg.read_text()
    assert text.count("# roundtable-managed begin") == 1
    assert text.count("# roundtable-managed end") == 1


def test_apply_preserves_user_blocks(tmp_path):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[profiles.my-custom]\n'
        'sandbox_mode = "read-only"\n'
        'approval_policy = "never"\n'
    )
    icp.cmd_apply(snippet, cfg, dry_run=False)
    text = cfg.read_text()
    assert "[profiles.my-custom]" in text
    assert "[profiles.roundtable-executor]" in text


def test_conflict_with_same_named_user_profile_aborts(tmp_path):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[profiles.roundtable-executor]\n'
        'sandbox_mode = "different"\n'
    )
    with pytest.raises(SystemExit):
        icp.cmd_apply(snippet, cfg, dry_run=False)


def test_remove_strips_managed_block(tmp_path):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[profiles.my-custom]\n'
        'sandbox_mode = "read-only"\n'
    )
    icp.cmd_apply(snippet, cfg, dry_run=False)
    icp.cmd_remove(cfg)
    text = cfg.read_text()
    assert "# roundtable-managed" not in text
    assert "[profiles.roundtable-executor]" not in text
    assert "[profiles.my-custom]" in text


def test_dry_run_does_not_write(tmp_path, capsys):
    snippet = tmp_path / "p.toml"
    snippet.write_text(SNIPPET)
    cfg = tmp_path / "config.toml"
    icp.cmd_apply(snippet, cfg, dry_run=True)
    out = capsys.readouterr().out
    assert "[profiles.roundtable-executor]" in out
    assert not cfg.exists()
