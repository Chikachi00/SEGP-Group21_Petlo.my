"""Score saved detector output against human-reviewed labels (precision / recall / F1 per class).

Use it to compare detector settings (baseline vs enhanced, confidence thresholds, tiling, a filter,
fine-tuned weights) on the SAME labelled frames, so a change is judged by numbers instead of by eye.

    python cv/evaluate_detections.py --training-dir data/training/001 --training-dir data/training/002 \
        --detections outputs/train-detect/001_front.jsonl --detections outputs/train-detect/001_side.jsonl \
        --detections outputs/train-detect/002_front.jsonl --detections outputs/train-detect/002_side.jsonl \
        --label baseline-enhanced

Read the results with these limits in mind:
* The labels started as drafts from a detector and were then corrected by hand, so a detector that
  produced the drafts looks slightly better than it deserves (annotators tend to accept its boxes).
* Never evaluate fine-tuned weights on frames they were trained on; use held-out sessions for that.
  Baseline weights (yolo11n.pt) were not trained on these frames, so comparing post-processing or
  settings on the baseline output is fair.
* Small label sets give noisy numbers: report the counts (TP/FP/FN) with every percentage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__:
    from .prelabel import CLASS_NAMES, DETECTOR_TO_CLASS, load_rows
else:
    from prelabel import CLASS_NAMES, DETECTOR_TO_CLASS, load_rows

DEFAULT_THRESHOLDS = (.1, .25, .4, .5)


def iou(a, b):
    """Intersection over union of two (x1, y1, x2, y2) boxes."""
    ix = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.


def read_label_boxes(path, width, height):
    """YOLO label file -> [(class_name, (x1, y1, x2, y2) in pixels)]."""
    boxes = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{Path(path).name}:{number}: expected 5 values, got {len(parts)}")
        class_id = int(parts[0])
        if not 0 <= class_id < len(CLASS_NAMES):
            raise ValueError(f"{Path(path).name}:{number}: unknown class {class_id}")
        xc, yc, w, h = (float(v) for v in parts[1:])
        boxes.append((CLASS_NAMES[class_id], ((xc - w / 2) * width, (yc - h / 2) * height,
                                                (xc + w / 2) * width, (yc + h / 2) * height)))
    return boxes


def predicted_boxes(detections):
    """Detector rows -> [(class_name, confidence, bbox)] using the project's class names."""
    out = []
    for d in detections:
        name = DETECTOR_TO_CLASS.get(d["label"])
        if name is not None:
            out.append((name, float(d["confidence"]), tuple(d["bbox"])))
    return out


def load_images(training_dirs, detection_paths, labels_subdir="labels"):
    """Pair every labelled image with the detector output for its frame."""
    images, missing_labels = [], []
    for training_dir in training_dirs:
        folder = Path(training_dir).resolve()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        by_video = {}
        for entry in manifest["images"]:
            by_video.setdefault(entry["video_id"], []).append(entry)
        rows_by_video = {}
        for path in detection_paths:
            video_id, rows = load_rows(path, by_video)
            if video_id is not None:
                rows_by_video[video_id] = rows
        for video_id, entries in by_video.items():
            rows = rows_by_video.get(video_id)
            if rows is None:
                raise ValueError(f"No detector output given for {video_id} in {folder.name}")
            for entry in entries:
                label_path = folder / labels_subdir / (Path(entry["image"]).stem + ".txt")
                if not label_path.is_file():
                    missing_labels.append(str(label_path))
                    continue
                row = rows.get(entry["frame_id"])
                if row is None:
                    raise ValueError(f"Detector output for {video_id} has no frame {entry['frame_id']}")
                images.append({"image": entry["image"], "video_id": video_id,
                               "truth": read_label_boxes(label_path, entry["width"], entry["height"]),
                               "predictions": predicted_boxes(row["detections"])})
    return images, missing_labels


def score_class(images, class_name, threshold, iou_threshold):
    tp = fp = fn = 0
    frames_with_truth = frames_hit = 0
    for item in images:
        truth = [box for name, box in item["truth"] if name == class_name]
        predictions = sorted(((conf, box) for name, conf, box in item["predictions"]
                              if name == class_name and conf >= threshold), key=lambda p: -p[0])
        matched, hits = set(), 0
        for conf, box in predictions:
            best, best_iou = None, iou_threshold
            for index, target in enumerate(truth):
                if index in matched:
                    continue
                value = iou(box, target)
                if value >= best_iou:
                    best, best_iou = index, value
            if best is None:
                fp += 1
            else:
                matched.add(best)
                hits += 1
        tp += hits
        fn += len(truth) - len(matched)
        if truth:
            frames_with_truth += 1
            frames_hit += 1 if hits else 0
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0. if tp + fp + fn else None)
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": f1, "frames_with_truth": frames_with_truth, "frames_hit": frames_hit}


def evaluate(images, thresholds=DEFAULT_THRESHOLDS, iou_threshold=.5, classes=CLASS_NAMES):
    result = {}
    for name in classes:
        rows = [score_class(images, name, t, iou_threshold) for t in thresholds]
        scored = [r for r in rows if r["f1"] is not None]
        result[name] = {"by_threshold": rows,
                        "best_f1": max(scored, key=lambda r: r["f1"]) if scored else None}
    return result


def _fmt(value):
    return "  n/a" if value is None else f"{value * 100:5.1f}"


def format_table(label, summary, iou_threshold, image_count):
    lines = [f"Detector evaluation: {label}   images={image_count}   IoU>={iou_threshold}",
             f"{'class':8} {'conf':>5} {'TP':>5} {'FP':>5} {'FN':>5} {'prec%':>6} {'rec%':>6} {'F1%':>6} {'frames hit':>11}"]
    for name, data in summary.items():
        for row in data["by_threshold"]:
            hit = f"{row['frames_hit']}/{row['frames_with_truth']}"
            lines.append(f"{name:8} {row['threshold']:5.2f} {row['tp']:5d} {row['fp']:5d} {row['fn']:5d} "
                         f"{_fmt(row['precision']):>6} {_fmt(row['recall']):>6} {_fmt(row['f1']):>6} {hit:>11}")
        best = data["best_f1"]
        if best:
            lines.append(f"{'':8} best F1 at confidence {best['threshold']:.2f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--training-dir", type=Path, action="append", required=True,
                        help="Session folder from build_training_frames.py with reviewed labels (repeat)")
    parser.add_argument("--detections", type=Path, action="append", required=True,
                        help="detect_disc_video.py JSONL, one per video (repeat)")
    parser.add_argument("--labels-subdir", default="labels")
    parser.add_argument("--iou", type=float, default=.5, help="Match threshold (default 0.5; try 0.3 for tiny discs)")
    parser.add_argument("--thresholds", default=",".join(str(t) for t in DEFAULT_THRESHOLDS),
                        help="Confidence thresholds to report, comma separated")
    parser.add_argument("--class", dest="classes", action="append", choices=CLASS_NAMES,
                        help="Only score this class (repeat); default all")
    parser.add_argument("--label", default="run", help="Name printed with the results")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    try:
        thresholds = tuple(float(t) for t in args.thresholds.split(",") if t.strip())
        if not thresholds or not 0 < args.iou <= 1:
            raise ValueError("Give at least one threshold and an IoU in (0, 1]")
        images, missing = load_images(args.training_dir, args.detections, args.labels_subdir)
        if not images:
            raise ValueError("No labelled images found; export reviewed labels into each session's labels folder")
        summary = evaluate(images, thresholds, args.iou, tuple(args.classes or CLASS_NAMES))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(format_table(args.label, summary, args.iou, len(images)))
    if missing:
        print(f"\nWarning: {len(missing)} images have no reviewed label file and were skipped (first: {missing[0]})")
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps({"label": args.label, "iou": args.iou, "images": len(images),
                                                "missing_labels": len(missing), "classes": summary}, indent=2) + "\n",
                                    encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
