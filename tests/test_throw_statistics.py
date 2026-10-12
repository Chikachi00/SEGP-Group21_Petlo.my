import copy
import json
from pathlib import Path
import tempfile
import unittest

from cv.build_throw_statistics import build, summarize


class ThrowStatisticsTests(unittest.TestCase):
    def sample(self):
        return {
            "schema_version": 1,
            "algorithm": "test-fusion",
            "source_sha256": {"front": "a", "side": "b"},
            "results": [
                {"sample_throw_id": "sample-throw-001", "outcome": "catch_success", "front_outcome": "catch_candidate", "side_outcome": "catch_candidate", "human_outcome": "miss"},
                {"sample_throw_id": "sample-throw-002", "outcome": "ground_pickup", "front_outcome": "ground_pickup_candidate", "side_outcome": "uncertain"},
                {"sample_throw_id": "sample-throw-003", "outcome": "miss_candidate", "front_outcome": "miss_candidate", "side_outcome": "uncertain"},
                {"sample_throw_id": "sample-throw-004", "outcome": "uncertain", "front_outcome": "uncertain", "side_outcome": "uncertain"},
            ],
        }

    def test_candidate_rates_separate_air_catches_and_retrievals(self):
        stats = summarize(self.sample())
        self.assertEqual(stats["total_throw_candidates"], 4)
        self.assertEqual(stats["classified_candidate_events"], 3)
        self.assertEqual(stats["uncertain_events"], 1)
        self.assertEqual(stats["candidate_counts"]["in_air_catch_candidate"], 1)
        self.assertEqual(stats["candidate_counts"]["ground_pickup_candidate"], 1)
        self.assertAlmostEqual(stats["candidate_coverage"], .75)
        self.assertAlmostEqual(stats["in_air_catch_candidate_rate"], 1 / 3)
        self.assertAlmostEqual(stats["retrieval_candidate_rate"], 2 / 3)
        self.assertFalse(stats["human_labels_used_for_statistics"])

    def test_uncertain_only_session_has_no_divide_by_zero_rates(self):
        payload = self.sample()
        payload["results"] = [{"sample_throw_id": "one", "outcome": "uncertain"}]
        stats = summarize(payload)
        self.assertEqual(stats["candidate_coverage"], 0)
        self.assertIsNone(stats["in_air_catch_candidate_rate"])
        self.assertIsNone(stats["retrieval_candidate_rate"])

    def test_unknown_outcome_and_duplicate_ids_are_rejected(self):
        payload = self.sample()
        payload["results"][0]["outcome"] = "maybe"
        with self.assertRaises(ValueError):
            summarize(payload)
        payload = self.sample()
        payload["results"][1]["sample_throw_id"] = payload["results"][0]["sample_throw_id"]
        with self.assertRaises(ValueError):
            summarize(payload)

    def test_build_writes_report_and_verifies_cache_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fused.json"
            source.write_text(json.dumps(self.sample()), encoding="utf-8")
            out = root / "statistics"
            first = build(source, out)
            self.assertEqual(first["cache"], "created")
            self.assertTrue((out / "statistics.html").is_file())
            second = build(source, out)
            self.assertEqual(second["cache"], "verified")
            (out / "statistics.html").write_text("manual edit", encoding="utf-8")
            with self.assertRaises(ValueError):
                build(source, out)

    def test_changed_input_does_not_overwrite_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fused.json"
            source.write_text(json.dumps(self.sample()), encoding="utf-8")
            out = root / "statistics"
            build(source, out)
            changed = self.sample()
            changed["results"] = changed["results"][:2]
            source.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build(source, out)


if __name__ == "__main__":
    unittest.main()
