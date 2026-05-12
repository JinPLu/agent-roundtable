from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from lessons_extract import extract_lessons  # noqa: E402
from lessons_inject import select_lessons  # noqa: E402


def _thread(project: pathlib.Path, slug: str) -> pathlib.Path:
    thread = project / ".roundtable" / "threads" / slug
    thread.mkdir(parents=True)
    return thread


def test_extract_writes_markdown_and_jsonl(tmp_path: pathlib.Path) -> None:
    thread = _thread(tmp_path, "demo-thread")
    (thread / "THREAD.md").write_text(
        """
## Turn 1
**Verification**: scope_check.py reported VIOLATION for docs/readme.md.
**Hand-off**: accept
""",
        encoding="utf-8",
    )

    lessons = extract_lessons(tmp_path, thread)

    assert len(lessons) == 1
    assert lessons[0]["tag"] == "scope"
    memory = tmp_path / ".roundtable" / "memory"
    assert "demo-thread" in (memory / "lessons.md").read_text(encoding="utf-8")
    line = json.loads((memory / "lessons.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["thread"] == "demo-thread"
    assert set(line) == {"thread", "ts", "tag", "lesson", "evidence_path", "applies_when"}


def test_extract_missing_thread_text_gracefully_returns_empty(tmp_path: pathlib.Path) -> None:
    thread = _thread(tmp_path, "empty-thread")

    lessons = extract_lessons(tmp_path, thread)

    assert lessons == []
    assert not (tmp_path / ".roundtable" / "memory" / "lessons.jsonl").exists()


def test_select_lessons_filters_by_keyword_and_recent_date(tmp_path: pathlib.Path) -> None:
    memory = tmp_path / ".roundtable" / "memory"
    memory.mkdir(parents=True)
    rows = [
        {
            "thread": "recent-match",
            "ts": "2026-05-11T00:00:00Z",
            "tag": "scope",
            "lesson": "Keep scope_check fixes inside allowed paths.",
            "evidence_path": "threads/recent",
            "applies_when": "scope_check allowed paths",
        },
        {
            "thread": "old-match",
            "ts": "2026-04-01T00:00:00Z",
            "tag": "scope",
            "lesson": "Old scope lesson.",
            "evidence_path": "threads/old",
            "applies_when": "scope_check",
        },
        {
            "thread": "recent-nomatch",
            "ts": "2026-05-11T00:00:00Z",
            "tag": "drift",
            "lesson": "Unrelated lesson.",
            "evidence_path": "threads/other",
            "applies_when": "routing",
        },
    ]
    (memory / "lessons.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    selected = select_lessons(tmp_path, "Fix scope_check allowed paths", now="2026-05-12T00:00:00Z", top_k=5)

    assert [item["thread"] for item in selected] == ["recent-match"]


def test_select_lessons_missing_memory_dir_returns_empty(tmp_path: pathlib.Path) -> None:
    assert select_lessons(tmp_path, "anything", now="2026-05-12T00:00:00Z") == []
