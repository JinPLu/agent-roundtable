import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_review_diversity import check_diversity, _extract_reviewer_actors

_SAME_VENDOR_THREAD = """
## Turn 1 — codex / reviewer — 2026-05-11T00:00:00Z
some content

## Turn 2 — codex / reviewer — 2026-05-11T00:01:00Z
some content
"""

_CROSS_VENDOR_THREAD = """
## Turn 1 — codex / reviewer — 2026-05-11T00:00:00Z
some content

## Turn 2 — claude / devils-advocate — 2026-05-11T00:01:00Z
some content
"""


def test_same_vendor_detects_warning(tmp_path):
    t = pathlib.Path(tmp_path) / "THREAD.md"
    t.write_text(_SAME_VENDOR_THREAD)
    ok, msg = check_diversity(pathlib.Path(tmp_path))
    assert ok is False
    assert "Same-vendor" in msg


def test_cross_vendor_passes(tmp_path):
    t = pathlib.Path(tmp_path) / "THREAD.md"
    t.write_text(_CROSS_VENDOR_THREAD)
    ok, msg = check_diversity(pathlib.Path(tmp_path))
    assert ok is True


def test_no_thread_md_passes(tmp_path):
    ok, msg = check_diversity(pathlib.Path(tmp_path))
    assert ok is True
    assert "not found" in msg


def test_fewer_than_two_reviewers_passes(tmp_path):
    t = pathlib.Path(tmp_path) / "THREAD.md"
    t.write_text("## Turn 1 — codex / reviewer — 2026-05-11T00:00:00Z\ncontent\n")
    ok, msg = check_diversity(pathlib.Path(tmp_path))
    assert ok is True
