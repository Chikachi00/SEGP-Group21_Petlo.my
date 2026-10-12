"""Track identity, prediction honesty, source-clock and end-to-end contracts."""
import copy
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from cv.dog_tracker import DogTracker, TrackingSettings, center, contract_row
from cv.track_dog_video import load_detections, run, sha256, write_json
from cv.video_tools.media import Toolchain, scan_video, extract_frames


def dog(x=100, confidence=.8, label="dog"):
    return {"label": label, "confidence": confidence, "bbox": [x, 100, x + 80, 160]}


class DogAssociationTests(unittest.TestCase):
    def initialized(self):
        tracker = DogTracker(1000, 600)
        for t in (0., .02, .04):
            state = tracker.update(t, [dog()])
        self.assertEqual(state["state"], "detected")
        return tracker

    def test_confirmation_rejects_one_frame_birth(self):
        tracker = DogTracker(1000, 600)
        self.assertEqual(tracker.update(0., [dog()])["state"], "acquiring")
        self.assertEqual(tracker.update(.02, [])["state"], "searching")
        self.assertIsNone(tracker.update(.04, [dog()])["track_id"])
        self.assertIsNone(tracker.update(.06, [dog()])["track_id"])
        self.assertEqual(tracker.update(.08, [dog()])["track_id"], "dog-001")

    def test_short_gap_preserves_id_without_fabricating_measurement(self):
        tracker = self.initialized()
        state = tracker.update(.14, [])
        self.assertEqual(state["state"], "predicted")
        self.assertIsNotNone(state["prediction_bbox"])
        row = contract_row("test", {"frame_id": 3, "t_sec": .14}, state)
        self.assertEqual(row["status"], "missing")
        self.assertIsNone(row["bbox"])
        self.assertIsNone(row["confidence"])
        back = tracker.update(.18, [dog()])
        self.assertEqual(back["track_id"], "dog-001")
        self.assertTrue(back["reacquired"])

    def test_prediction_expires_before_identity_then_restarts(self):
        tracker = self.initialized()
        state = tracker.update(.4, [])
        self.assertEqual(state["state"], "lost")
        self.assertIsNone(state["prediction_bbox"])
        self.assertEqual(state["track_id"], "dog-001")
        state = tracker.update(.9, [dog(700)])
        self.assertEqual(state["retired_track_id"], "dog-001")
        self.assertIsNone(state["track_id"])
        tracker.update(.92, [dog(700)])
        self.assertEqual(tracker.update(.94, [dog(700)])["track_id"], "dog-002")

    def test_vfr_prediction_uses_elapsed_seconds(self):
        tracker = DogTracker(1000, 600, TrackingSettings(confirm_samples=1))
        tracker.update(0., [dog(100)])
        tracker.update(.1, [dog(110)])
        a = tracker.update(.15, [])
        b = tracker.update(.30, [])
        ax = center(a["prediction_bbox"])[0] - 150
        bx = center(b["prediction_bbox"])[0] - 150
        self.assertGreater(ax, 0)
        self.assertAlmostEqual(bx / ax, 4.)

    def test_distant_high_confidence_outlier_cannot_take_id(self):
        tracker = self.initialized()
        state = tracker.update(.06, [dog(850, .99)])
        self.assertEqual(state["state"], "predicted")
        self.assertEqual(state["reason"], "no_candidate_in_gate")
        state = tracker.update(.08, [dog(101, .5), dog(850, .99)])
        self.assertEqual(state["bbox"], dog(101)["bbox"])

    def test_person_box_never_becomes_dog_measurement(self):
        tracker = self.initialized()
        state = tracker.update(.06, [dog(label="person")])
        self.assertEqual(state["state"], "predicted")
        self.assertIsNone(state["bbox"])

    def test_ambiguous_dogs_do_not_force_assignment(self):
        tracker = self.initialized()
        state = tracker.update(.06, [dog(99), dog(101)])
        self.assertEqual(state["reason"], "ambiguous_candidates")
        self.assertIsNone(state["bbox"])

    def test_invalid_clock_box_and_settings_fail(self):
        tracker = self.initialized()
        for t in (.04, .01, float("nan")):
            with self.assertRaises(ValueError):
                tracker.update(t, [])
        with self.assertRaises(ValueError):
            tracker.update(.06, [dog(-1)])
        with self.assertRaises(ValueError):
            TrackingSettings(prediction_sec=1, identity_gap_sec=.75)


class TrackingMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.tools = Toolchain.discover()
        except (ValueError, RuntimeError, OSError) as exc:
            raise unittest.SkipTest(str(exc))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dog-tracking-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "raw" / "dog.mkv"
        self.source.parent.mkdir()
        subprocess.run([self.tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=96x64:rate=10:duration=1", "-vf", "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,4)+eq(n\\,9)",
                        "-fps_mode", "vfr", "-c:v", "ffv1", str(self.source)], capture_output=True, check=True)
        metadata, self.index, _ = scan_video(self.source, self.tools)
        self.pack = self.root / "pack"
        self.pack.mkdir()
        write_json(self.pack / "frame_index.json", self.index)
        self.video = {"id": "dog", "source": str(self.source), "source_sha256": sha256(self.source), "status": "complete", "role": "action",
                      "width": 96, "height": 64, "frames_count": 4, "duration": metadata["duration"],
                      "paths": {"frame_index": "frame_index.json"}, "metadata": metadata}
        write_json(self.pack / "manifest.json", {"videos": [self.video]})
        self.det = self.root / "detections.jsonl"
        self.rows = [{"video_id": "dog", **r, "detections": [{"label": "dog", "bbox": [10, 10, 30, 30], "confidence": .8}] if i != 2 else []}
                     for i, r in enumerate(self.index)]
        self.det.write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        self.report = {"status": "complete", "source": str(self.source), "source_sha256": sha256(self.source), "video_id": "dog",
                       "first_frame": self.index[0], "last_frame": self.index[-1],
                       "counts": {"processed_frames": 4, "dog_frames": 3, "disc_frames": 0, "person_frames": 0}}
        write_json(self.det.with_suffix(".json"), self.report)

    def test_real_vfr_render_review_schema_cache_and_original_content(self):
        output = self.root / "result"
        before = sha256(self.source)
        settings = TrackingSettings(confirm_samples=1)
        summary = run(self.det, self.pack, output, settings, Path(self.tools.ffmpeg).parent)
        self.assertEqual(summary["processed_frames"], 4)
        rows = [json.loads(r) for r in (output / "tracks.jsonl").read_text().splitlines()]
        self.assertEqual([r["t_sec"] for r in rows], [r["t_sec"] for r in self.index])
        self.assertEqual(rows[2]["status"], "missing")
        self.assertIsNone(rows[2]["bbox"])
        self.assertEqual(rows[3]["track_id"], "dog-002")
        with (output / "trajectory.csv").open(newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        self.assertEqual(csv_rows[2]["measured_x_px"], "")
        self.assertEqual(len(csv_rows[2]), 11)
        self.assertEqual(sha256(self.source), before)
        self.assertEqual(run(self.det, self.pack, output, settings, Path(self.tools.ffmpeg).parent)["cache_key"], summary["cache_key"])
        (output / "trajectory.csv").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Cached output changed"):
            run(self.det, self.pack, output, settings, Path(self.tools.ffmpeg).parent)

    def test_changed_time_order_or_source_provenance_rejected(self):
        for change in ("time", "order", "provenance", "count"):
            rows, report = copy.deepcopy(self.rows), copy.deepcopy(self.report)
            if change == "time":
                rows[1]["t_sec"] += .01
            elif change == "order":
                rows[0], rows[1] = rows[1], rows[0]
            elif change == "count":
                report["counts"]["dog_frames"] += 1
            else:
                report["source_sha256"] = "0" * 64
            self.det.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            write_json(self.det.with_suffix(".json"), report)
            with self.assertRaises(ValueError, msg=change):
                load_detections(self.det, self.pack)

    def test_long_continuous_and_sparse_windows_do_not_exhaust_filter_parser(self):
        source = self.source.with_name("long.mkv")
        subprocess.run([self.tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=96x64:rate=60:duration=6", "-c:v", "ffv1", str(source)], capture_output=True, check=True)
        _, frames, _ = scan_video(source, self.tools)
        for name, selected in (("continuous", frames[:150]), ("sparse", frames[::2])):
            images = extract_frames(source, selected, self.root / name, self.tools)
            self.assertEqual([r["frame_id"] for r in images], [r["frame_id"] for r in selected])
            self.assertEqual([r["pts_sec"] for r in images], [r["pts_sec"] for r in selected])


if __name__ == "__main__":
    unittest.main()
