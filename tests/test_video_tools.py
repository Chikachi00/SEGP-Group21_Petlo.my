"""Behavior tests using small real CFR/VFR/rotated/static videos.

No sample source files are changed. Set VIDEO_TOOLS_FFMPEG_DIR when the
portable binaries are not discoverable. All media fixtures live in tempfile.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image
import numpy as np


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_index(path):
    """The package's JSON indexes may be arrays or a named index object."""
    result = _read_json(path)
    if isinstance(result, list):
        return result
    for key in ("frames", "images", "records"):
        if key in result:
            return result[key]
    raise AssertionError(f"No frame records in {path}")


class VideoFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = importlib.import_module("cv.video_tools.media")
        cls.prepare_module = importlib.import_module("cv.video_tools.prepare")
        ffmpeg_dir = os.environ.get("VIDEO_TOOLS_FFMPEG_DIR")
        if not ffmpeg_dir:
            root = Path(__file__).resolve().parents[1]
            candidates = sorted(root.glob("tools/ffmpeg/**/ffmpeg.exe"))
            if candidates:
                ffmpeg_dir = str(candidates[0].parent)
        try:
            cls.tools = cls.media.Toolchain.discover(ffmpeg_dir)
        except (OSError, RuntimeError, ValueError) as exc:
            raise unittest.SkipTest(f"FFmpeg/ffprobe unavailable: {exc}")
        cls.temp = tempfile.TemporaryDirectory(prefix="video-tools-contracts-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "sources"
        cls.source.mkdir()
        cls.ffmpeg = cls.tools.ffmpeg
        cls.cfr = cls.source / "Front_Tripod_CFR.mp4"
        cls.vfr = cls.source / "Handheld_VFR.mkv"
        cls.static = cls.source / "Setup_static.mkv"
        cls.rotated = cls.source / "Rotated_Handheld.mp4"
        hevc_source = cls.root / "hevc-input"
        hevc_source.mkdir()
        cls.hevc = hevc_source / "hevc_hvc1.mp4"

        cls._encode(["-f", "lavfi", "-i", "testsrc2=size=96x64:rate=6:duration=2",
                     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"], cls.cfr)
        cls._encode(["-f", "lavfi", "-i", "testsrc2=size=96x64:rate=10:duration=1",
                     "-vf", "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,4)+eq(n\\,9)",
                     "-fps_mode", "vfr", "-c:v", "ffv1"], cls.vfr)
        cls._encode(["-f", "lavfi", "-i", "color=c=red:size=96x64:rate=4:duration=1",
                     "-c:v", "ffv1"], cls.static)
        unrotated = cls.root / "quadrants.mp4"
        cls._encode(["-f", "lavfi", "-i", "color=c=red:size=96x64:rate=4:duration=1",
                     "-vf", "drawbox=x=48:y=0:w=48:h=32:color=lime:t=fill,"
                            "drawbox=x=0:y=32:w=48:h=32:color=blue:t=fill,"
                            "drawbox=x=48:y=32:w=48:h=32:color=yellow:t=fill",
                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10"], unrotated)
        cls._encode(["-display_rotation", "90", "-i", str(unrotated), "-c", "copy"], cls.rotated)
        cls._encode(["-f", "lavfi", "-i", "testsrc2=size=96x64:rate=4:duration=1",
                     "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "pools=none",
                     "-tag:v", "hvc1"], cls.hevc)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    @classmethod
    def _encode(cls, args, target):
        proc = subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                               "-y", *args, str(target)], capture_output=True, text=True, timeout=60)
        if proc.returncode:
            raise RuntimeError(f"Synthetic fixture failed: {proc.stderr}")

    def _scan(self, source):
        return self.media.scan_video(source, self.tools)


class RealMediaContracts(VideoFixtures):
    def test_cfr_indexes_all_source_frames_and_distinct_images(self):
        source_hash = hashlib.sha256(self.cfr.read_bytes()).hexdigest()
        metadata, frames, _ = self._scan(self.cfr)
        self.assertEqual(len(frames), 12)
        self.assertEqual([row["frame_id"] for row in frames], list(range(12)))
        self.assertAlmostEqual(frames[6]["t_sec"], 1.0, places=5)
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            images = self.media.extract_frames(self.cfr, [frames[i] for i in (0, 6, 11)],
                                               Path(out), self.tools, max_side=1280)
            self.assertEqual([x["frame_id"] for x in images], [0, 6, 11])
            fingerprints = []
            for row in images:
                with Image.open(row["path"]) as im:
                    self.assertEqual(im.size, (metadata["width"], metadata["height"]))
                    fingerprints.append(hashlib.sha256(im.tobytes()).hexdigest())
                self.assertAlmostEqual(row["t_sec"], frames[row["frame_id"]]["t_sec"], places=5)
            self.assertEqual(len(set(fingerprints)), 3, "Changing timestamps returned duplicate source pixels")
        self.assertEqual(hashlib.sha256(self.cfr.read_bytes()).hexdigest(), source_hash)

    def test_vfr_keeps_real_timestamps_and_never_inserts_frames(self):
        _, frames, _ = self._scan(self.vfr)
        self.assertEqual(len(frames), 4)
        np.testing.assert_allclose([r["t_sec"] for r in frames], [0.0, 0.1, 0.4, 0.9], atol=0.001)
        deltas = np.diff([r["t_sec"] for r in frames])
        self.assertGreater(float(np.max(deltas) - np.min(deltas)), 0.2)
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            images = self.media.extract_frames(self.vfr, [frames[1], frames[3]], Path(out), self.tools, max_side=1280)
            self.assertEqual([r["frame_id"] for r in images], [1, 3])
            np.testing.assert_allclose([r["t_sec"] for r in images], [0.1, 0.9], atol=0.001)

    def test_static_identical_pixels_are_valid_separate_source_frames(self):
        _, frames, motion = self._scan(self.static)
        self.assertEqual(len(frames), 4)
        self.assertEqual(len(set(r["t_sec"] for r in frames)), 4)
        self.assertTrue(all(r["motion_score"] < 0.001 for r in motion))
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            images = self.media.extract_frames(self.static, frames, Path(out), self.tools, max_side=1280)
            hashes = []
            for row in images:
                with Image.open(row["path"]) as im:
                    hashes.append(hashlib.sha256(im.tobytes()).hexdigest())
            self.assertEqual(len(hashes), 4)
            self.assertEqual(len(set(hashes)), 1)

    def test_rotation_applies_display_dimensions_and_pixel_orientation(self):
        metadata, frames, _ = self._scan(self.rotated)
        self.assertEqual((metadata["encoded_width"], metadata["encoded_height"]), (96, 64))
        self.assertEqual((metadata["width"], metadata["height"]), (64, 96))
        self.assertEqual(abs(metadata["rotation"]), 90)
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            image = self.media.extract_frames(self.rotated, frames[:1], Path(out), self.tools, max_side=1280)[0]
            self.assertEqual((image["source_width"], image["source_height"]), (64, 96))
            self.assertEqual(image["crop"], [0, 0, 64, 96])
            with Image.open(image["path"]) as im:
                self.assertEqual(im.size, (64, 96))
                # 90-degree MP4 display matrix places the original top-right (green)
                # quadrant at the display top-left, independently of frame shape.
                rgb = np.asarray(im.convert("RGB"))[10, 10]
                self.assertGreater(int(rgb[1]), 180)
                self.assertLess(int(rgb[0]), 70)
                self.assertLess(int(rgb[2]), 70)

    def test_hvc1_decodes_entire_stream(self):
        metadata, frames, _ = self._scan(self.hevc)
        self.assertEqual(metadata["codec_name"], "hevc")
        self.assertEqual(len(frames), 4)
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            images = self.media.extract_frames(self.hevc, [frames[0], frames[-1]], Path(out), self.tools, max_side=1280)
            self.assertEqual(len(images), 2)
            for row in images:
                with Image.open(row["path"]) as im:
                    im.verify()

    def test_scaled_view_coordinates_round_trip_to_original_pixels(self):
        metadata, frames, _ = self._scan(self.rotated)
        with tempfile.TemporaryDirectory(dir=self.root) as out:
            row = self.media.extract_frames(self.rotated, frames[:1], Path(out), self.tools, max_side=48)[0]
            self.assertEqual((row["width"], row["height"]), (32, 48))
            self.assertEqual((row["source_width"], row["source_height"]), (64, 96))
            self.assertEqual(row["crop"], [0, 0, 64, 96])
            self.assertAlmostEqual(row["width"] / row["scale_x"], metadata["width"])
            self.assertAlmostEqual(row["height"] / row["scale_y"], metadata["height"])
            with Image.open(row["path"]) as im:
                self.assertEqual(im.size, (32, 48))


class PackageContracts(VideoFixtures):
    def test_invalid_video_is_reported_without_hiding_valid_video(self):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            temp_root = Path(tmp)
            source = temp_root / "input"
            source.mkdir()
            (source / "Front_Tripod.mp4").write_bytes(self.cfr.read_bytes())
            (source / "broken.mp4").write_bytes(b"This is not an MP4 file.")
            manifest = self.prepare_module.prepare(source, temp_root / "pack", self.tools)
            self.assertEqual(len(manifest["videos"]), 2)
            statuses = {Path(v["source"]).name: v for v in manifest["videos"]}
            self.assertEqual(statuses["Front_Tripod.mp4"]["status"], "complete")
            self.assertEqual(statuses["broken.mp4"]["status"], "failed")
            self.assertTrue(statuses["broken.mp4"]["error"])

    def test_output_cannot_be_inside_read_only_source_directory(self):
        forbidden_output = self.source / "should-not-be-created"
        with self.assertRaises((ValueError, RuntimeError)):
            self.prepare_module.prepare(self.source, forbidden_output, self.tools)
        self.assertFalse(forbidden_output.exists())

    def test_cache_reuses_complete_package_and_repairs_missing_overview(self):
        out = self.root / "cache-pack"
        first = self.prepare_module.prepare(self.source, out, self.tools)
        self.assertEqual(len(first["videos"]), 4)
        self.assertTrue(all(v["status"] == "complete" for v in first["videos"]))
        overview = out / first["videos"][0]["paths"]["overview"]
        frame_index = out / first["videos"][0]["paths"]["frame_index"]
        before = (overview.stat().st_mtime_ns, frame_index.stat().st_mtime_ns)
        second = self.prepare_module.prepare(self.source, out, self.tools)
        self.assertEqual(before, (overview.stat().st_mtime_ns, frame_index.stat().st_mtime_ns))
        self.assertEqual([v["status"] for v in second["videos"]], ["complete"] * 4)
        overview.unlink()
        third = self.prepare_module.prepare(self.source, out, self.tools)
        self.assertTrue(overview.exists())
        self.assertTrue(all(v["status"] == "complete" for v in third["videos"]))
        with Image.open(overview) as im:
            im.verify()

    def test_inspection_half_open_time_bounds_and_crop_mapping(self):
        # A saved source frame should match every crop in display coordinates.
        inspect_module = importlib.import_module("cv.video_tools.inspect")
        out = self.root / "inspect-pack"
        manifest = self.prepare_module.prepare(self.source, out, self.tools)
        video = next(v for v in manifest["videos"] if "CFR" in Path(v["source"]).name)
        video_id = video.get("video_id", video.get("id"))
        report = inspect_module.inspect_window(out, video_id, 0.0, 0.5, self.tools,
                                               sampling="source", tiles=True, frame_id=1)
        self.assertEqual([x["frame_id"] for x in report["images"]], [1])
        self.assertEqual(len(report["crops"]), 16)
        self.assertTrue(all(len(batch["images"]) <= 8 for batch in report["batches"]))
        image_record = report["images"][0]
        with Image.open(image_record["path"]) as full:
            full_pixels = np.asarray(full.convert("RGB"), dtype=float)
        for crop in report["crops"]:
            x, y, width, height = crop["crop"]
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
            self.assertLessEqual(x + width, image_record["source_width"])
            self.assertLessEqual(y + height, image_record["source_height"])
            with Image.open(crop["path"]) as tile:
                self.assertEqual(tile.size, (width, height))
                # JPEG re-encoding may differ; broad pixel agreement catches
                # transposed coordinates, incorrect parent frames and offsets.
                diff = np.abs(np.asarray(tile.convert("RGB"), dtype=float) - full_pixels[y:y+height, x:x+width])
                self.assertLess(float(np.mean(diff)), 25)
            self.assertAlmostEqual((crop["width"] / crop["scale_x"]) + x, x + width)
            self.assertAlmostEqual((crop["height"] / crop["scale_y"]) + y, y + height)
            self.assertEqual(crop["frame_id"], 1)
            self.assertEqual(Path(crop["parent_path"]), Path(image_record["path"]))
        dense = inspect_module.inspect_window(out, video_id, 0.0, 0.5, self.tools, sampling="source")
        self.assertTrue(Path(dense["output_dir"]).is_dir())
        self.assertEqual(Path(dense["report_path"]).parent, Path(dense["output_dir"]))
        reused = inspect_module.inspect_window(out, video_id, 0.0, 0.5, self.tools, sampling="source")
        self.assertTrue(reused["cached"])
        self.assertEqual(reused["output_dir"], dense["output_dir"])
        self.assertEqual([x["frame_id"] for x in dense["images"]], [0, 1, 2])
        self.assertTrue(all(x["t_sec"] < 0.5 for x in dense["images"]))
        sparse_video = next(v for v in manifest["videos"] if "VFR" in Path(v["source"]).name)
        sparse = inspect_module.inspect_window(out, sparse_video["id"], 0.0, 1.0, self.tools, sampling="10")
        self.assertEqual([x["frame_id"] for x in sparse["images"]], [0, 1, 2, 3])
        np.testing.assert_allclose([r["t_sec"] for r in sparse["images"]], [0.0, 0.1, 0.4, 0.9], atol=0.001)
        bbox = inspect_module.inspect_window(out, video_id, 0.0, 0.5, self.tools, frame_id=1,
                                             bboxes=[{"frame_id": 1, "bbox": [20, 16, 60, 40], "label": "dog"}])
        self.assertEqual(bbox["crops"][0]["crop"], [10, 10, 60, 36])
        self.assertEqual(bbox["crops"][0]["label"], "dog")
        self.assertAlmostEqual(3 / bbox["crops"][0]["scale_x"] + bbox["crops"][0]["crop"][0], 13)
        for update in ({"frame_id": True}, {"frame_id": 3}, {"tiles": True}):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    inspect_module.inspect_window(out, video_id, 0.0, 0.5, self.tools, **update)


class TrackingContracts(unittest.TestCase):
    def setUp(self):
        self.review_module = importlib.import_module("cv.video_tools.review")
        self.frames = [{"frame_id": i, "t_sec": t, "pts_sec": t, "timestamp_source": "pts"}
                       for i, t in enumerate((0.0, 0.1, 0.4, 0.9))]
        self.manifest = {"videos": [{"id": "v", "width": 100, "height": 100,
                                     "status": "complete", "frames_count": 4,
                                     "role": "context", "source": "unused-context.mp4",
                                     "paths": {"frame_index": "frames.json", "candidates": "candidates.json"}}]}
        self.row = {"video_id": "v", "frame_id": 2, "t_sec": 0.4, "label": "disc",
                    "track_id": "disc-1", "bbox": [10, 20, 25, 35], "confidence": 0.8,
                    "status": "detected"}

    def validate(self, rows):
        return self.review_module.validate_results(rows, self.manifest, {"v": self.frames})

    def test_valid_results_use_source_timestamps_and_allow_unknown_confidence(self):
        rounded = {**self.row, "t_sec": 0.4007, "confidence": None}
        result = self.validate([rounded])
        self.assertEqual(result[0]["t_sec"], 0.4)
        self.assertIsNone(result[0]["confidence"])
        missing = {**self.row, "status": "missing", "bbox": None, "confidence": None}
        self.assertIsNone(self.validate([missing])[0]["bbox"])
        self.assertEqual(self.validate([{**missing, "confidence": 0.2}])[0]["confidence"], 0.2)
        with self.assertRaises(ValueError):
            self.validate([{**missing, "confidence": 1.1}])

    def test_invalid_source_coordinates_ids_and_times_are_rejected(self):
        changes = [
            {"video_id": "unknown"}, {"frame_id": 20}, {"frame_id": True},
            {"t_sec": 0.1}, {"t_sec": float("nan")}, {"track_id": True},
            {"label": "ball"}, {"status": "guess"}, {"confidence": -0.1},
            {"confidence": 1.1}, {"confidence": float("inf")},
            {"bbox": None}, {"bbox": [25, 20, 10, 35]},
            {"bbox": [10, 20, 10, 35]}, {"bbox": [-1, 20, 25, 35]},
            {"bbox": [10, 20, 101, 35]}, {"bbox": [10, 20, 25, float("nan")]},
            {"status": "missing", "bbox": [10, 20, 25, 35], "confidence": None},
            {"extra": "undocumented"},
        ]
        for update in changes:
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    self.validate([{**self.row, **update}])
        incomplete = copy.deepcopy(self.row)
        del incomplete["bbox"]
        with self.assertRaises(ValueError):
            self.validate([incomplete])
        with self.assertRaises(ValueError):
            self.validate([self.row, self.row])

    def test_review_comparison_accepts_renamed_tracks_but_rejects_changed_coverage(self):
        # Context-only manifest keeps this a report/validation test. Rendering
        # actual source frames is exercised separately in PackageContracts.
        with tempfile.TemporaryDirectory(prefix="video-review-contracts-") as tmp:
            root = Path(tmp)
            # Only source identity is relevant to comparison in this isolated
            # context-only test; actual decoding is covered by video fixtures.
            source = root / "source-identity.dat"
            source.write_bytes(b"Stable source content for review comparison.")
            self.manifest["videos"][0]["source"] = str(source)
            self.manifest["videos"][0]["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            (root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
            (root / "frames.json").write_text(json.dumps(self.frames), encoding="utf-8")
            (root / "candidates.json").write_text("[]", encoding="utf-8")
            rows = [{**self.row, "frame_id": f["frame_id"], "t_sec": f["t_sec"]} for f in self.frames]
            rows[1] = {**rows[1], "status": "missing", "bbox": None, "confidence": None}
            first_input = root / "first.jsonl"
            first_input.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            first = self.review_module.review(root, first_input, tools=None, processing_seconds=2.0)
            previous = Path(first["output_dir"]) / "report.json"
            renamed = [{**self.row, "frame_id": f["frame_id"], "t_sec": f["t_sec"], "track_id": "renamed-42"}
                       for f in self.frames]
            second_input = root / "second.jsonl"
            second_input.write_text("\n".join(json.dumps(r) for r in renamed), encoding="utf-8")
            second = self.review_module.review(root, second_input, tools=None, previous_path=previous,
                                               processing_seconds=1.0)
            self.assertEqual(second["comparison"]["status"], "compatible")
            self.assertEqual(second["comparison"]["deltas"]["missing_record_count"]["delta"], -1)
            self.assertEqual(second["comparison"]["deltas"]["processing_seconds"]["delta"], -1.0)
            second_input.write_text("\n".join(json.dumps(r) for r in renamed[:-1]), encoding="utf-8")
            less_coverage = self.review_module.review(root, second_input, tools=None, previous_path=previous)
            self.assertEqual(less_coverage["comparison"]["status"], "incompatible")
            self.assertNotIn("deltas", less_coverage["comparison"])
            source.write_bytes(b"Changed source; old frame index is no longer trusted.")
            with self.assertRaises(ValueError):
                self.review_module.review(root, second_input, tools=None, previous_path=previous)

    def test_malformed_jsonl_does_not_create_partial_review(self):
        with tempfile.TemporaryDirectory(prefix="video-review-invalid-") as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
            (root / "frames.json").write_text(json.dumps(self.frames), encoding="utf-8")
            bad = root / "invalid.jsonl"
            # A duplicate JSON key should not silently replace the first value.
            bad.write_text('{"video_id":"v","video_id":"other"}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                self.review_module.review(root, bad, tools=None)
            self.assertFalse((root / "reviews").exists())


if __name__ == "__main__":
    unittest.main()
