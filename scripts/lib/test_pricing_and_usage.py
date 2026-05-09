"""Tests for the pricing snapshot loader and usage-log helpers.

Pinned to the vendored snapshot and synthetic records so they pass on a fresh
clone before any real dispatches have been logged.
"""
import json
import pathlib
import tempfile
import unittest

from scripts.lib import pricing_snapshot, usage_log


class TestPricingSnapshot(unittest.TestCase):
    def test_load_snapshot_returns_models(self):
        snap = pricing_snapshot.load_snapshot()
        models = snap.get("_models", {})
        self.assertGreaterEqual(len(models), 10, "snapshot should whitelist >= 10 models")

    def test_get_model_pricing_resolves_known_id(self):
        snap = pricing_snapshot.load_snapshot()
        models = snap.get("_models", {})
        priced = [
            mid for mid, ent in models.items()
            if not mid.startswith("_") and not ent.get("_no_litellm_source")
        ]
        self.assertTrue(priced, "snapshot should contain at least one priced model")
        pricing = pricing_snapshot.get_model_pricing(priced[0])
        self.assertIsNotNone(pricing, f"{priced[0]} should resolve")

    def test_marker_only_entries_return_none(self):
        snap = pricing_snapshot.load_snapshot()
        markers = [
            mid for mid, ent in snap.get("_models", {}).items()
            if ent.get("_no_litellm_source")
        ]
        if markers:
            # Marker-only entries (Cursor variants) intentionally return None;
            # the estimator falls back to models.json for those.
            self.assertIsNone(pricing_snapshot.get_model_pricing(markers[0]))

    def test_unknown_model_returns_none(self):
        self.assertIsNone(pricing_snapshot.get_model_pricing("does-not-exist-xyz-9999"))


class TestUsageLog(unittest.TestCase):
    def _record(self, **overrides):
        rec = {
            "ts": "2026-05-10T00:00:00Z",
            "thread": "test-thread",
            "actor": "codex",
            "model": "gpt-5.5",
            "role": "executor",
            "effort": "medium",
            "prompt_tokens": 50_000,
            "completion_tokens": 6_000,
            "reasoning_tokens": 0,
            "cost_estimated_usd": 0.30,
            "cost_actual_usd": 0.34,
            "elapsed_s": 60,
            "exit_code": 0,
        }
        rec.update(overrides)
        return rec

    def test_append_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            log = pathlib.Path(d) / "usage.log"
            for i in range(3):
                usage_log.append_usage_record(
                    self._record(prompt_tokens=10_000 * (i + 1)), log_path=log
                )
            rows = usage_log.read_usage_log(log_path=log)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["prompt_tokens"], 10_000)
            self.assertEqual(rows[2]["prompt_tokens"], 30_000)

    def test_append_writes_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            log = pathlib.Path(d) / "usage.log"
            usage_log.append_usage_record(self._record(), log_path=log)
            content = log.read_text(encoding="utf-8")
            for line in content.strip().splitlines():
                json.loads(line)

    def test_recalibrate_refuses_low_sample(self):
        records = [
            self._record(role="executor", prompt_tokens=p, completion_tokens=c)
            for p, c in [(50_000, 5_000), (60_000, 7_000)]
        ]
        current = {
            "executor": {"input": 80_000, "output_chat": 8_000, "output_thinking": 25_000}
        }
        suggested = usage_log.recalibrate_role_budgets(records, current)
        # With only 2 samples (<5), budgets should be unchanged or marked as
        # under-sampled. We accept either behaviour as long as we don't silently
        # adopt the small sample.
        if "executor" in suggested:
            self.assertEqual(
                suggested["executor"].get("input"),
                current["executor"]["input"],
                "small-sample cells must not overwrite",
            )


if __name__ == "__main__":
    unittest.main()
