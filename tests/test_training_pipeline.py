import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from cv.build_training_frames import detector_candidates, motion_peaks, select_frames
from cv.make_dataset import assign_splits, assign_time_blocks, build, parse_label_file, tile_labels
from cv.prelabel import draft_lines, run as prelabel, yolo_line
from cv.train_detector import build_train_kwargs, read_names, resolve_dataset


def index(n=600, fps=30.):
    return [{"frame_id": i, "t_sec": i / fps, "pts_sec": i / fps} for i in range(n)]


def motion_with_peaks(n=600, fps=30., peaks=(100, 300, 500)):
    out = []
    for i in range(n):
        score = .001 + sum(.2 for p in peaks if abs(i - p) < 5)
        out.append({"frame_id": i, "t_sec": i / fps, "pts_sec": i / fps, "motion_score": score})
    return out


def rows(n=600, fps=30., disc_frames=range(100, 140), weak=range(200, 210)):
    result = []
    for i in range(n):
        dets = []
        if i in disc_frames:
            dets.append({"label": "disc", "bbox": [10, 10, 20, 20], "confidence": .8})
        if i in weak:
            dets.append({"label": "disc", "bbox": [10, 10, 20, 20], "confidence": .3})
        result.append({"frame_id": i, "t_sec": i / fps, "detections": dets})
    return result


class SelectionTests(unittest.TestCase):
    def test_motion_peaks_rank_highest_first(self):
        ranked = motion_peaks(motion_with_peaks())
        self.assertTrue(any(abs(ranked[0] - p) < 6 for p in (100, 300, 500)))

    def test_detector_candidates(self):
        found = detector_candidates(rows(disc_frames=range(100, 140), weak=range(200, 210)))
        self.assertTrue(all(f in range(200, 210) for f in found["low_confidence_disc"]))
        self.assertTrue(found["disc_gap"])
        # misses are only reported close to a confident detection (within 0.5 s = 15 frames)
        self.assertTrue(all(85 <= f < 155 for f in found["disc_gap"]))

    def test_budget_min_gap_and_uniqueness(self):
        chosen = select_frames(index(), motion_with_peaks(), rows(), max_frames=30, min_gap_sec=.5)
        self.assertLessEqual(len(chosen), 30)
        times = sorted(f / 30. for f in chosen)
        self.assertTrue(all(b - a >= .5 - 1e-6 for a, b in zip(times, times[1:])))
        self.assertGreater(len(chosen), 10)

    def test_every_reason_is_used_when_available_and_uniform_is_capped(self):
        chosen = select_frames(index(1800), motion_with_peaks(1800, peaks=range(100, 1800, 150)),
                               rows(1800, disc_frames=range(100, 400), weak=range(500, 600)),
                               max_frames=40, min_gap_sec=.4)
        reasons = set(chosen.values())
        self.assertTrue({"motion", "disc_gap", "low_confidence_disc", "uniform"} <= reasons)
        self.assertLessEqual(list(chosen.values()).count("uniform"), 10)

    def test_without_detector_output_motion_and_uniform_still_work(self):
        chosen = select_frames(index(), motion_with_peaks(), None, max_frames=20)
        self.assertTrue(chosen)
        self.assertFalse({"disc_gap", "low_confidence_disc"} & set(chosen.values()))

    def test_static_video_is_not_flooded(self):
        static = [{"frame_id": i, "t_sec": i / 30, "pts_sec": i / 30, "motion_score": 0.} for i in range(3000)]
        chosen = select_frames(index(3000), static, None, max_frames=150, min_gap_sec=.4, uniform_step_sec=5.)
        self.assertLessEqual(len(chosen), 38)   # uniform cap only: 25% of 150

    def test_invalid_budget(self):
        with self.assertRaises(ValueError):
            select_frames(index(), [], None, max_frames=0)


class LabelTests(unittest.TestCase):
    def test_yolo_line_normalises_and_clips(self):
        self.assertEqual(yolo_line(2, [100, 50, 200, 150], 1000, 500), "2 0.150000 0.200000 0.100000 0.200000")
        self.assertEqual(yolo_line(0, [-20, 0, 20, 10], 100, 100), "0 0.100000 0.050000 0.200000 0.100000")
        self.assertIsNone(yolo_line(0, [10, 10, 10.5, 30], 100, 100))

    def test_draft_lines_map_disc_to_frisbee_and_filter_confidence(self):
        dets = [{"label": "disc", "bbox": [0, 0, 10, 10], "confidence": .9},
                {"label": "dog", "bbox": [0, 0, 50, 50], "confidence": .1},
                {"label": "person", "bbox": [0, 0, 50, 50], "confidence": .5}]
        lines = draft_lines(dets, 100, 100, .25)
        self.assertEqual([l.split()[0] for l in lines], ["2", "0"])

    def test_parse_label_file_validation(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.txt"
            p.write_text("2 0.5 0.5 0.2 0.2\n\n0 0.5 0.5 1.0 1.0\n")
            self.assertEqual(len(parse_label_file(p)), 2)
            for bad in ("3 0.5 0.5 0.2 0.2", "1 0.5 0.5 0.2", "1 0.95 0.5 0.2 0.2", "1 0.5 0.5 0 0.2",
                        "x 0.5 0.5 0.2 0.2", "1 0.5 0.5 nan 0.2"):
                p.write_text(bad + "\n")
                with self.assertRaises(ValueError, msg=bad):
                    parse_label_file(p)

    def test_tile_labels_clip_and_drop_mostly_cut_boxes(self):
        # 1000x500 frame; tile covers x 0..600. Box A fully inside, B straddles (30% inside), C outside.
        boxes = [(2, .1, .5, .02, .04), (1, .62, .5, .1, .2), (0, .9, .5, .1, .1)]
        out = tile_labels(boxes, 1000, 500, (0, 0, 600, 500))
        self.assertEqual([b[0] for b in out], [2])
        self.assertAlmostEqual(out[0][1], 100 / 600)
        inside = tile_labels([(1, .55, .5, .1, .2)], 1000, 500, (0, 0, 600, 500), min_visible=.5)
        self.assertEqual(len(inside), 1)
        self.assertLessEqual(inside[0][1] + inside[0][3] / 2, 1 + 1e-9)


class SplitTests(unittest.TestCase):
    def test_sessions_never_straddle_splits_and_all_splits_exist(self):
        groups = [f"s{i}" for i in range(10)]
        a = assign_splits(groups, seed=1)
        self.assertEqual(a, assign_splits(groups, seed=1))
        self.assertEqual(set(a.values()), {"train", "val", "test"})
        self.assertEqual(len(a), 10)

    def test_too_few_sessions_is_refused(self):
        with self.assertRaisesRegex(ValueError, "at least 3"):
            assign_splits(["a", "b"])

    def test_time_block_fallback_is_available(self):
        entries = [{"session": "s", "video_id": "v", "t_sec": float(t)} for t in range(0, 200, 5)]
        blocks = assign_time_blocks(entries, block_sec=20.)
        self.assertEqual(set(blocks.values()), {"train", "val", "test"})


class DatasetBuildTests(unittest.TestCase):
    def make_session(self, root, name, count=2, label_lines="2 0.5 0.5 0.05 0.05\n1 0.3 0.3 0.2 0.2\n", draft_only=False):
        folder = root / name
        (folder / "frames").mkdir(parents=True)
        (folder / ("labels_draft" if draft_only else "labels")).mkdir()
        images = []
        for i in range(count):
            frame = np.full((200, 400, 3), 90, np.uint8)
            cv2.imwrite(str(folder / "frames" / f"v__f{i:06d}.jpg"), frame)
            (folder / ("labels_draft" if draft_only else "labels") / f"v__f{i:06d}.txt").write_text(label_lines)
            images.append({"image": f"frames/v__f{i:06d}.jpg", "video_id": "v", "session": name, "frame_id": i,
                           "pts_sec": i / 30, "t_sec": i / 30, "reason": "motion", "width": 400, "height": 200,
                           "source_sha256": "a" * 64})
        (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "session": name, "images": images}))
        return folder

    def test_end_to_end_split_tiles_yaml_and_report(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            sessions = [self.make_session(root, f"s{i}") for i in range(4)]
            out, yaml = root / "dataset", root / "data" / "dataset.yaml"
            report = build(sessions, out, yaml, seed=3, tiles=True)
            self.assertEqual(report["split_method"], "by_session")
            placed = {}
            for split in ("train", "val", "test"):
                for p in (out / "images" / split).glob("*.jpg"):
                    placed.setdefault(p.name.split("__")[0], set()).add(split)
            self.assertTrue(all(len(v) == 1 for v in placed.values()))   # no session in two splits
            self.assertGreater(sum(c["tiles"] for c in report["counts"].values()), 0)
            for split in ("train", "val", "test"):
                for img in (out / "images" / split).glob("*.jpg"):
                    self.assertTrue((out / "labels" / split / (img.stem + ".txt")).is_file())
            names, splits = read_names(yaml)
            self.assertEqual(names, ["person", "dog", "frisbee"])
            self.assertEqual(splits["train"], "../dataset/images/train")
            counts = resolve_dataset(yaml, root / "resolved.yaml")
            self.assertGreater(counts["train"], 0)
            with self.assertRaisesRegex(ValueError, "already exists"):
                build(sessions, out, yaml)

    def test_drafts_missing_labels_and_bad_labels_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            drafts = [self.make_session(root, f"d{i}", draft_only=True) for i in range(3)]
            with self.assertRaisesRegex(ValueError, "labels_draft"):
                build(drafts, root / "o1", root / "y1.yaml", labels_subdir="labels_draft")
            with self.assertRaisesRegex(ValueError, "No reviewed labels"):
                build(drafts, root / "o2", root / "y2.yaml")      # 'labels' folder is empty
            bad = [self.make_session(root, f"b{i}", label_lines="9 0.5 0.5 0.1 0.1\n") for i in range(3)]
            with self.assertRaisesRegex(ValueError, "class 9"):
                build(bad, root / "o3", root / "y3.yaml")

    def test_two_sessions_need_explicit_leaky_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            two = [self.make_session(root, "a", count=40), self.make_session(root, "b", count=40)]
            with self.assertRaisesRegex(ValueError, "at least 3"):
                build(two, root / "o1", root / "y1.yaml")
            report = build(two, root / "o2", root / "y2.yaml", allow_time_block_split=True, block_sec=.5)
            self.assertEqual(report["split_method"], "time_blocks_LEAKY")
            self.assertTrue(any("optimistic" in w for w in report["warnings"]))


class PrelabelTests(unittest.TestCase):
    def test_drafts_written_and_mismatched_detector_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            folder = root / "s"
            (folder / "frames").mkdir(parents=True)
            entries = [{"image": f"frames/v__f{i:06d}.jpg", "video_id": "v", "session": "s", "frame_id": i,
                        "pts_sec": i / 30, "t_sec": i / 30, "width": 400, "height": 200, "source_sha256": "h"}
                       for i in (3, 9)]
            (folder / "manifest.json").write_text(json.dumps({"session": "s", "images": entries}))
            det = root / "d.jsonl"
            det.write_text("".join(json.dumps({"frame_id": e["frame_id"], "t_sec": e["t_sec"], "video_id": "v",
                            "detections": [{"label": "disc", "bbox": [10, 10, 30, 30], "confidence": .7}]}) + "\n"
                           for e in entries))
            det.with_suffix(".json").write_text(json.dumps({"status": "complete", "video_id": "v", "source_sha256": "h"}))
            result = prelabel(folder, [det], cvat_zip=root / "cvat.zip")
            self.assertEqual(result["drafts"], 2)
            self.assertTrue((folder / "labels_draft" / "v__f000003.txt").read_text().startswith("2 "))
            self.assertFalse((folder / "labels").exists())                  # drafts never land in labels/
            det.with_suffix(".json").write_text(json.dumps({"status": "complete", "video_id": "v", "source_sha256": "other"}))
            with self.assertRaisesRegex(ValueError, "does not match"):
                prelabel(folder, [det])


class TrainArgsTests(unittest.TestCase):
    def test_small_object_settings(self):
        args = SimpleNamespace(epochs=50, imgsz=1280, batch=4, device="0", seed=7, patience=20, project="runs",
                               name="x", freeze=10, workers=2, close_mosaic=10, lr0=.005)
        kw = build_train_kwargs(args, "d.yaml")
        self.assertEqual((kw["imgsz"], kw["mosaic"], kw["copy_paste"], kw["seed"]), (1280, 1.0, 0., 7))
        self.assertTrue(kw["deterministic"])
        self.assertFalse(kw["exist_ok"])

    def test_wrong_class_order_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for s in ("train", "val"):
                (root / "images" / s).mkdir(parents=True)
                cv2.imwrite(str(root / "images" / s / "a.jpg"), np.zeros((8, 8, 3), np.uint8))
            (root / "d.yaml").write_text("train: images/train\nval: images/val\nnames:\n  0: dog\n  1: disc\n")
            with self.assertRaisesRegex(ValueError, "classes must be"):
                resolve_dataset(root / "d.yaml", root / "out.yaml")


if __name__ == "__main__":
    unittest.main()
