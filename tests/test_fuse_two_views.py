import json
from pathlib import Path
import tempfile
import unittest

from cv.build_throw_statistics import sha256, summarize
from cv.fuse_two_views import FusionSettings, fuse_events, fuse_outcome, run

CATCH, PICKUP, UNSURE = "catch_candidate", "ground_pickup_candidate", "uncertain"


def event(number, start, outcome=CATCH, release=True):
    return {"throw_id": f"throw-{number:03d}", "start_sec": start, "end_sec": start + 2.,
            "predicted_outcome": outcome,
            "release_evidence": {"departure_sec": start + .2} if release else None}


def shifted(events, offset, prefix="s"):
    return [dict(e, throw_id=f"{prefix}-{e['throw_id']}", start_sec=e["start_sec"] + offset,
                 end_sec=e["end_sec"] + offset,
                 release_evidence={"departure_sec": e["release_evidence"]["departure_sec"] + offset}
                 if e["release_evidence"] else None) for e in events]


class OutcomeTests(unittest.TestCase):
    def test_agreement_categories(self):
        self.assertEqual(fuse_outcome(CATCH, CATCH), (CATCH, "corroborated"))
        self.assertEqual(fuse_outcome(CATCH, UNSURE), (CATCH, "single_view_evidence"))
        self.assertEqual(fuse_outcome(None, PICKUP), (PICKUP, "single_view_evidence"))
        self.assertEqual(fuse_outcome(CATCH, PICKUP), (UNSURE, "conflict"))
        self.assertEqual(fuse_outcome(UNSURE, UNSURE), (UNSURE, "no_evidence"))
        self.assertEqual(fuse_outcome(UNSURE, None), (UNSURE, "no_evidence"))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.front = [event(1, 3.), event(2, 11., PICKUP), event(3, 20.), event(4, 31.)]

    def test_offset_is_recovered_and_events_paired_by_time(self):
        side = shifted(self.front, .35)
        sync, rows = fuse_events(self.front, side)
        self.assertEqual(sync["status"], "estimated")
        self.assertAlmostEqual(sync["offset_sec"], .35, places=3)
        self.assertEqual(sync["matched_pairs"], 4)
        self.assertTrue(all(r["views"] == "both" and r["agreement"] == "corroborated" for r in rows))

    def test_event_order_is_not_used_when_a_view_has_extra_or_missing_events(self):
        side = shifted(self.front, -.4)
        side = [event(99, .5, CATCH)] + side[:2] + side[3:]   # spurious early event, throw 3 missing
        sync, rows = fuse_events(self.front, side)
        self.assertEqual(sync["status"], "estimated")
        self.assertAlmostEqual(sync["offset_sec"], -.4, places=3)
        views = [r["views"] for r in rows]
        self.assertEqual(views.count("both"), 3)
        self.assertEqual(views.count("front"), 1)   # throw 3 only front
        self.assertEqual(views.count("side"), 1)    # spurious side event kept as single-view
        single = [r for r in rows if r["views"] != "both"]
        self.assertTrue(all(r["agreement"] == "single_view_evidence" for r in single))

    def test_uncertain_in_one_view_is_resolved_by_the_other_and_conflict_stays_uncertain(self):
        front = [event(1, 3., CATCH), event(2, 11., CATCH), event(3, 20., PICKUP)]
        side = shifted([event(1, 3., UNSURE), event(2, 11., PICKUP), event(3, 20., PICKUP)], .3)
        _, rows = fuse_events(front, side)
        self.assertEqual([r["outcome"] for r in rows], [CATCH, UNSURE, PICKUP])
        self.assertEqual([r["agreement"] for r in rows], ["single_view_evidence", "conflict", "corroborated"])
        self.assertTrue(rows[1]["conflict"])

    def test_offset_beyond_limit_or_tolerance_is_not_forced(self):
        side = shifted(self.front, 7.)
        sync, rows = fuse_events(self.front, side)
        self.assertEqual(sync["status"], "unreliable")
        self.assertEqual(sync["fallback_view"], "front")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["views"] == "front" for r in rows))

    def test_inconsistent_timing_is_unreliable_not_merged(self):
        side = [event(1, 3.4), event(2, 15.), event(3, 26.)]
        sync, rows = fuse_events(self.front, side)
        self.assertEqual(sync["status"], "unreliable")   # only one pair fits; two required
        self.assertEqual(sync["fallback_view"], "front")

    def test_empty_view_falls_back_without_error(self):
        sync, rows = fuse_events(self.front, [])
        self.assertEqual(sync["status"], "unreliable")
        self.assertEqual(len(rows), 4)
        sync, rows = fuse_events([], shifted(self.front, 1.))
        self.assertEqual(sync["fallback_view"], "side")
        self.assertEqual(len(rows), 4)

    def test_single_event_pair_is_only_weak(self):
        sync, rows = fuse_events([event(1, 3.)], shifted([event(1, 3.)], .5))
        self.assertEqual(sync["status"], "weak")
        self.assertEqual(rows[0]["views"], "both")

    def test_manual_offset_hint_overrides_estimation(self):
        side = shifted(self.front, 1.5)
        sync, rows = fuse_events(self.front, side, FusionSettings(offset_hint_sec=1.5))
        self.assertEqual(sync["status"], "manual")
        self.assertEqual(sync["offset_sec"], 1.5)
        self.assertEqual(sync["matched_pairs"], 4)
        sync, rows = fuse_events(self.front, side, FusionSettings(offset_hint_sec=0.))
        self.assertEqual(sync["matched_pairs"], 0)   # wrong hint cannot be silently corrected

    def test_release_only_in_one_view_uses_common_start_time(self):
        side = shifted(self.front, .3)
        for e in side:
            e["release_evidence"] = None
        sync, _ = fuse_events(self.front, side)
        self.assertAlmostEqual(sync["offset_sec"], .3, places=3)

    def test_rows_are_accepted_by_statistics_and_ids_are_unique(self):
        side = shifted(self.front, .35)
        _, rows = fuse_events(self.front, side[:3])
        stats = summarize({"schema_version": 1, "results": rows})
        self.assertEqual(stats["total_throw_candidates"], 4)
        self.assertEqual(len({r["sample_throw_id"] for r in rows}), 4)

    def test_invalid_settings(self):
        for kwargs in ({"tolerance_sec": 0}, {"max_offset_sec": float("nan")}, {"min_pairs": 0},
                       {"min_pairs": True}, {"offset_hint_sec": float("inf")}):
            with self.assertRaises(ValueError):
                FusionSettings(**kwargs)


class RunTests(unittest.TestCase):
    def make_run(self, root, name, view, events, digest, camera="tripod"):
        folder = root / name
        folder.mkdir()
        (folder / "events-v3.json").write_text(json.dumps(
            {"schema_version": 3, "video_id": f"{view}-video", "event_candidates": events}), encoding="utf-8")
        (folder / "summary.json").write_text(json.dumps(
            {"status": "complete", "video_id": f"{view}-video", "cache_key": f"{view}-key",
             "provenance": {"camera": camera, "source_sha256": digest},
             "artifact_sha256": {"events-v3.json": sha256(folder / "events-v3.json")}}), encoding="utf-8")
        return folder

    def test_end_to_end_cache_protection_and_input_checks(self):
        base = [event(1, 3.), event(2, 11., PICKUP), event(3, 20.)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            front = self.make_run(root, "front", "front", base, "a" * 64)
            side = self.make_run(root, "side", "side", shifted(base, .35), "b" * 64)
            result = run(front, side, root / "out")
            self.assertEqual(result["sync"]["status"], "estimated")
            saved = json.loads((root / "out" / "fused-results.json").read_text())
            self.assertEqual(saved["cache_key"], result["cache_key"])
            self.assertEqual(len(saved["results"]), 3)
            with self.assertRaisesRegex(ValueError, "already exists"):
                run(front, side, root / "out")
            (side / "events-v3.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Modified"):
                run(front, side, root / "out2")

    def test_same_source_and_non_tripod_runs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            front = self.make_run(root, "front", "front", [event(1, 3.)], "a" * 64)
            same = self.make_run(root, "side", "side", [event(1, 3.)], "a" * 64)
            with self.assertRaisesRegex(ValueError, "same source"):
                run(front, same, root / "out")
            handheld = self.make_run(root, "hand", "side", [event(1, 3.)], "c" * 64, camera="handheld")
            with self.assertRaisesRegex(ValueError, "tripod"):
                run(front, handheld, root / "out2")


if __name__ == "__main__":
    unittest.main()
