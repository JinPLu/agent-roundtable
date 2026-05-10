import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_budget import check_budget


def test_no_ledger_is_ok(tmp_path):
    ok, total, msg = check_budget(pathlib.Path(tmp_path))
    assert ok is True
    assert total == 0.0


def test_under_budget(tmp_path):
    ledger = pathlib.Path(tmp_path) / ".budget_ledger.jsonl"
    ledger.write_text('{"ts":"2026-05-11T00:00:00Z","role":"executor","model":"x","est_usd":0.5}\n')
    ok, total, msg = check_budget(pathlib.Path(tmp_path), max_usd=1.0)
    assert ok is True
    assert abs(total - 0.5) < 0.001


def test_over_budget(tmp_path):
    ledger = pathlib.Path(tmp_path) / ".budget_ledger.jsonl"
    ledger.write_text('{"ts":"2026-05-11T00:00:00Z","role":"executor","model":"x","est_usd":2.0}\n')
    ok, total, msg = check_budget(pathlib.Path(tmp_path), max_usd=1.0)
    assert ok is False
    assert "BUDGET EXCEEDED" in msg


def test_budget_file_read(tmp_path):
    ledger = pathlib.Path(tmp_path) / ".budget_ledger.jsonl"
    ledger.write_text('{"ts":"t","role":"r","model":"m","est_usd":0.1}\n')
    budget_file = pathlib.Path(tmp_path) / ".budget"
    budget_file.write_text("0.05\n")
    ok, total, msg = check_budget(pathlib.Path(tmp_path))
    assert ok is False  # 0.1 > 0.05
