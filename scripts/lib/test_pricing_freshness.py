import pathlib, json, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_pricing_freshness import check_freshness
from datetime import date, timedelta


def _make_registry(as_of, pinned: bool = False, tmp_path=None):
    reg = {
        "active": {"codex": "my-model", "claude": None},
        "models": {
            "my-model": {
                "actor": "codex",
                "pricing": {"per_1m_input": 1.0, "_as_of": as_of, "_pinned": pinned}
                if as_of else {"per_1m_input": 1.0},
            }
        },
    }
    p = pathlib.Path(tmp_path) / "models.json"
    p.write_text(json.dumps(reg))
    return p


def test_fresh_pricing_passes(tmp_path):
    p = _make_registry(date.today().isoformat(), tmp_path=tmp_path)
    assert check_freshness(p, interactive=False) is True


def test_stale_pricing_non_interactive_fails(tmp_path):
    stale = (date.today() - timedelta(days=60)).isoformat()
    p = _make_registry(stale, tmp_path=tmp_path)
    assert check_freshness(p, interactive=False) is False


def test_pinned_pricing_skipped(tmp_path):
    stale = (date.today() - timedelta(days=60)).isoformat()
    p = _make_registry(stale, pinned=True, tmp_path=tmp_path)
    assert check_freshness(p, interactive=False) is True


def test_no_as_of_passes(tmp_path):
    p = _make_registry(None, tmp_path=tmp_path)
    assert check_freshness(p, interactive=False) is True
