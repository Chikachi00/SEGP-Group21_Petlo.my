import json
from pathlib import Path
import tempfile
import unittest

from cv.evaluate_detections import (evaluate, iou, load_images, predicted_boxes, read_label_boxes, score_class)

SHA = "a" * 64


def det(label, bbox, conf):
    return {"label": label, "bbox": list(bbox), "confidence": conf}


def session(root, rows_by_frame, labels, video="vid", size=(100, 100), missing_label_for=None):
    """Write a minimal training session + detector run; returns (training_dir, jsonl_path)."""
    folder = Path(root) / "sess"
    (folder / "labels").mkdir(parents=True)
    images = []
    for frame_id in rows_by_frame:
        name = f"{video}__f{frame_id:06d}"
        images.append({"image": f"frames/{name}.jpg", "video_id": video, "frame_id": frame_id, "t_sec": frame_id / 10,
                       "width": size[0], "height": size[1], "source_sha256": SHA})
        if frame_id != missing_label_for:
            (folder / "labels" / f"{name}.txt").write_text("".join(l + "\n" for l in labels.get(frame_id, [])))
    (folder / "manifest.json").write_text(json.dumps({"session": "sess", "images": images}))
    jsonl = Path(root) / f"{video}.jsonl"
    jsonl.write_text("".join(json.dumps({"frame_id": f, "t_sec": f / 10, "detections": d}) + "\n"
                             for f, d in rows_by_frame.items()))
    jsonl.with_suffix(".json").write_text(json.dumps({"status": "complete", "video_id": video, "source_sha256": SHA}))
    return folder, jsonl


class GeometryTests(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.)
        self.assertAlmostEqual(iou((0, 0, 10, 10), (5, 0, 15, 10)), 1 / 3)
        self.assertEqual(iou((0, 0, 1, 1), (5, 5, 6, 6)), 0.)

    def test_label_boxes_are_converted_to_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("2 0.5 0.5 0.2 0.1\n")
            (name, box), = read_label_boxes(path, 200, 100)
            self.assertEqual(name, "frisbee")
            for got, want in zip(box, (80., 45., 120., 55.)):
                self.assertAlmostEqual(got, want)

    def test_bad_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("2 0.5 0.5\n")
            with self.assertRaises(ValueError):
                read_label_boxes(path, 10, 10)

    def test_detector_labels_map_to_project_classes(self):
        got = predicted_boxes([det("disc", (0, 0, 1, 1), .5), det("bird", (0, 0, 1, 1), .9)])
        self.assertEqual([g[0] for g in got], ["frisbee"])


class ScoringTests(unittest.TestCase):
    def image(self, truth, preds):
        return {"truth": truth, "predictions": preds}

    def test_perfect_miss_and_false_positive(self):
        box = (10, 10, 20, 20)
        images = [self.image([("frisbee", box)], [("frisbee", .9, box)]),              # hit
                  self.image([("frisbee", box)], []),                                    # miss
                  self.image([], [("frisbee", .8, box)])]                               # false positive
        row = score_class(images, "frisbee", .25, .5)
        self.assertEqual((row["tp"], row["fp"], row["fn"]), (1, 1, 1))
        self.assertAlmostEqual(row["precision"], .5)
        self.assertAlmostEqual(row["recall"], .5)
        self.assertEqual((row["frames_hit"], row["frames_with_truth"]), (1, 2))

    def test_confidence_threshold_removes_weak_predictions(self):
        box = (10, 10, 20, 20)
        images = [self.image([("frisbee", box)], [("frisbee", .3, box)])]
        self.assertEqual(score_class(images, "frisbee", .25, .5)["tp"], 1)
        row = score_class(images, "frisbee", .5, .5)
        self.assertEqual((row["tp"], row["fn"]), (0, 1))

    def test_one_truth_box_cannot_be_matched_twice(self):
        box = (10, 10, 20, 20)
        images = [self.image([("frisbee", box)], [("frisbee", .9, box), ("frisbee", .8, (10, 10, 20, 21))])]
        row = score_class(images, "frisbee", .25, .5)
        self.assertEqual((row["tp"], row["fp"], row["fn"]), (1, 1, 0))

    def test_classes_are_scored_separately(self):
        box = (10, 10, 20, 20)
        images = [self.image([("dog", box)], [("person", .9, box)])]
        summary = evaluate(images, (.25,), .5)
        self.assertEqual(summary["dog"]["by_threshold"][0]["fn"], 1)
        self.assertEqual(summary["person"]["by_threshold"][0]["fp"], 1)

    def test_empty_class_has_no_scores_not_zero(self):
        row = score_class([self.image([], [])], "frisbee", .25, .5)
        self.assertIsNone(row["precision"])
        self.assertIsNone(row["recall"])


class EndToEndTests(unittest.TestCase):
    def test_load_and_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = {0: [det("disc", (45, 45, 55, 55), .9)], 1: [det("disc", (5, 5, 10, 10), .9)]}
            labels = {0: ["2 0.5 0.5 0.1 0.1"], 1: ["2 0.5 0.5 0.1 0.1"]}
            folder, jsonl = session(tmp, rows, labels)
            images, missing = load_images([folder], [jsonl])
            self.assertEqual((len(images), missing), (2, []))
            row = evaluate(images, (.25,), .5, ("frisbee",))["frisbee"]["by_threshold"][0]
            self.assertEqual((row["tp"], row["fp"], row["fn"]), (1, 1, 1))

    def test_missing_label_files_are_reported_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = {0: [], 1: []}
            folder, jsonl = session(tmp, rows, {}, missing_label_for=1)
            images, missing = load_images([folder], [jsonl])
            self.assertEqual(len(images), 1)
            self.assertEqual(len(missing), 1)

    def test_detector_run_for_another_video_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, jsonl = session(tmp, {0: []}, {})
            with self.assertRaises(ValueError):
                load_images([folder], [])

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, jsonl = session(tmp, {0: []}, {})
            report = jsonl.with_suffix(".json")
            report.write_text(json.dumps({"status": "complete", "video_id": "vid", "source_sha256": "b" * 64}))
            with self.assertRaises(ValueError):
                load_images([folder], [jsonl])


if __name__ == "__main__":
    unittest.main()
