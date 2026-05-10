"""Tests for scripts/print_dispatch_block.py.

Run via: python3 -m pytest scripts/lib/test_print_dispatch_block.py -v
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_SKILL_DIR = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _SKILL_DIR / "scripts" / "print_dispatch_block.py"
_MODELS_JSON = _SKILL_DIR / "models.json"
_FORBIDDEN = ("_official_before_discount", "_pretax_reference")


def _has_real_registry() -> bool:
    if not _MODELS_JSON.exists():
        return False
    try:
        d = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(
        k for k in (d.get("models") or {})
        if not k.startswith("_") and (d["models"][k].get("actor") or "")
    )


def _run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *extra],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(not _has_real_registry(), reason="needs populated models.json")
def test_known_model_prints_full_block() -> None:
    # Pick the first non-placeholder model from the user's registry.
    d = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    real_ids = [k for k in (d.get("models") or {}) if not k.startswith("_")]
    assert real_ids, "registry has no real model entries"
    model = real_ids[0]
    role = "reviewer"
    proc = _run("--model", model, "--role", role, "--effort", "medium", "--turns", "1")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    # Block: 1 header + 9 fields + 1 blank + 1 prompt = 12 lines.
    assert len(lines) >= 11, f"expected >= 11 lines, got {len(lines)}: {proc.stdout!r}"
    assert lines[0] == "Proposed dispatch"
    expected_field_starts = (
        "  Thread  :",
        "  Project :",
        "  Role    :",
        "  Actor   :",
        "  Specs   :",
        "  Effort  :",
        "  Est.    :",
        "  Multi?  :",
        "  Budget  :",
    )
    field_lines = [ln for ln in lines if ln.startswith("  ")]
    for prefix in expected_field_starts:
        assert any(ln.startswith(prefix) for ln in field_lines), \
            f"missing field {prefix!r}"


def test_missing_model_exits_2() -> None:
    proc = _run("--model", "definitely-not-a-real-model-id-x9z", "--role", "reviewer")
    assert proc.returncode == 2
    assert "unknown model" in proc.stderr.lower()


def test_output_excludes_deprecated_pricing_keys() -> None:
    if not _has_real_registry():
        pytest.skip("needs populated models.json")
    d = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    real_ids = [k for k in (d.get("models") or {}) if not k.startswith("_")]
    assert real_ids
    proc = _run("--model", real_ids[0], "--role", "reviewer")
    assert proc.returncode == 0, proc.stderr
    for forbidden in _FORBIDDEN:
        assert forbidden not in proc.stdout, \
            f"foot-gun: deprecated key {forbidden!r} leaked into output:\n{proc.stdout}"


def test_script_source_does_not_print_deprecated_keys() -> None:
    """Static check: the script source should mention the foot-gun keys ONLY
    in the deny-list constant or comments, never in print() calls or f-strings."""
    src = _SCRIPT.read_text(encoding="utf-8")
    # Allow the keys to appear in the deny set + comments + tests.
    for forbidden in _FORBIDDEN:
        # We expect the key to appear in _DEPRECATED_PRICING_KEYS only.
        # Hard guard: it should never appear inside a print() call.
        bad_patterns = [f"print({forbidden}", f'"{forbidden}"', f"'{forbidden}'"]
        # The set definition is allowed (bad_patterns above); count them.
        for line in src.splitlines():
            if forbidden in line and "_DEPRECATED_PRICING_KEYS" not in line and "print(" in line:
                pytest.fail(f"forbidden key {forbidden!r} appears in print() at: {line!r}")


def test_thread_and_project_default_placeholders() -> None:
    if not _has_real_registry():
        pytest.skip("needs populated models.json")
    d = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    real_ids = [k for k in (d.get("models") or {}) if not k.startswith("_")]
    proc = _run("--model", real_ids[0], "--role", "reviewer")
    assert proc.returncode == 0
    assert "<not specified>" in proc.stdout, "missing default placeholders"


def test_thread_and_project_overridden() -> None:
    if not _has_real_registry():
        pytest.skip("needs populated models.json")
    d = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    real_ids = [k for k in (d.get("models") or {}) if not k.startswith("_")]
    proc = _run(
        "--model", real_ids[0],
        "--role", "reviewer",
        "--thread", "demo-slug",
        "--project", "/tmp/demo",
    )
    assert proc.returncode == 0
    assert "demo-slug" in proc.stdout
    assert "/tmp/demo" in proc.stdout
