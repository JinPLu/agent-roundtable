"""Tests for research_cache.py."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from research_cache import (  # noqa: E402
    _CACHE_FILENAME,
    _CACHE_TTL_HOURS,
    _sha256_file,
    _write_cache,
    ensure_research_baseline,
)


def _make_models_json(tmp_path: pathlib.Path, content: str = '{"models": {}}') -> pathlib.Path:
    p = tmp_path / "models.json"
    p.write_text(content, encoding="utf-8")
    return p


def _make_thread_dir(tmp_path: pathlib.Path, slug: str = "t1") -> pathlib.Path:
    d = tmp_path / ".roundtable" / "threads" / slug
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Test 1: first write — cache is created after successful freshness check
# ---------------------------------------------------------------------------

def test_first_write(tmp_path: pathlib.Path) -> None:
    models = _make_models_json(tmp_path)
    thread_dir = _make_thread_dir(tmp_path)

    with patch("research_cache.check_freshness", return_value=True):
        ret = ensure_research_baseline(thread_dir, models_json=models)

    assert ret == 0
    cache_path = thread_dir / _CACHE_FILENAME
    assert cache_path.exists()
    data = json.loads(cache_path.read_text())
    assert data["snapshot_hash"] == _sha256_file(models)
    assert "checked_at" in data


# ---------------------------------------------------------------------------
# Test 2: cache hit — freshness not re-checked
# ---------------------------------------------------------------------------

def test_cache_hit(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    models = _make_models_json(tmp_path)
    thread_dir = _make_thread_dir(tmp_path)

    # Pre-write a fresh cache
    _write_cache(thread_dir / _CACHE_FILENAME, _sha256_file(models))

    with patch("research_cache.check_freshness") as mock_cf:
        ret = ensure_research_baseline(thread_dir, models_json=models)

    assert ret == 0
    mock_cf.assert_not_called()  # should not have called check_freshness
    out = capsys.readouterr().out
    assert out.startswith("CACHE_HIT")


# ---------------------------------------------------------------------------
# Test 3: hash change invalidates cache and triggers re-check
# ---------------------------------------------------------------------------

def test_hash_change_invalidates(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    models = _make_models_json(tmp_path)
    thread_dir = _make_thread_dir(tmp_path)

    # Write cache with a stale (wrong) hash
    cache_path = thread_dir / _CACHE_FILENAME
    cache_path.write_text(
        json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "snapshot_hash": "deadbeef"}),
        encoding="utf-8",
    )

    with patch("research_cache.check_freshness", return_value=True):
        ret = ensure_research_baseline(thread_dir, models_json=models)

    assert ret == 0
    out = capsys.readouterr().out
    assert "CACHE_INVALIDATED" in out
    assert "hash_changed" in out
    # Cache should now have the correct hash
    updated = json.loads(cache_path.read_text())
    assert updated["snapshot_hash"] == _sha256_file(models)


# ---------------------------------------------------------------------------
# Test 4: TTL expiry invalidates cache
# ---------------------------------------------------------------------------

def test_ttl_expiry_invalidates(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    models = _make_models_json(tmp_path)
    thread_dir = _make_thread_dir(tmp_path)

    old_time = (datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS + 1)).isoformat()
    cache_path = thread_dir / _CACHE_FILENAME
    cache_path.write_text(
        json.dumps({"checked_at": old_time, "snapshot_hash": _sha256_file(models)}),
        encoding="utf-8",
    )

    with patch("research_cache.check_freshness", return_value=True):
        ret = ensure_research_baseline(thread_dir, models_json=models)

    assert ret == 0
    out = capsys.readouterr().out
    assert "CACHE_INVALIDATED" in out
    assert "expired" in out


# ---------------------------------------------------------------------------
# Test 5: stale pricing returns exit 1
# ---------------------------------------------------------------------------

def test_stale_pricing_returns_one(tmp_path: pathlib.Path) -> None:
    models = _make_models_json(tmp_path)
    thread_dir = _make_thread_dir(tmp_path)

    with patch("research_cache.check_freshness", return_value=False):
        ret = ensure_research_baseline(thread_dir, models_json=models)

    assert ret == 1
    # Cache must NOT be written on stale result
    assert not (thread_dir / _CACHE_FILENAME).exists()
