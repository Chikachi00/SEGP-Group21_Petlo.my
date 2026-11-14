"""Turn saved detector output into DRAFT YOLO labels for human review.

Drafts inherit the detector's blind spots (missed or blurred discs), so a person must
review every image and add what is missing. Draft files are written to labels_draft/,
never to labels/, and make_dataset.py refuses to build from a drafts folder.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

CLASS_NAMES = ("person", "dog", "frisbee")          # order = class IDs in data/dataset.yaml
DETECTOR_TO_CLASS = {"person": "person", "dog": "dog", "disc": "frisbee"}


def yolo_line(class_id, bbox, width, height):
    """Format one display-oriented pixel box as a normalized YOLO line; None if degenerate."""
    x1, y1 = max(0., bbox[0]), max(0., bbox[1])
    x2, y2 = min(float(width), bbox[2]), min(float(height), bbox[3])
    if x2 - x1 < 1. or y2 - y1 < 1.:
        return None
    return (f"{class_id} {(x1 + x2) / 2 / width:.6f} {(y1 + y2) / 2 / height:.6f} "
            f"{(x2 - x1) / width:.6f} {(y2 - y1) / height:.6f}")


def draft_lines(detections, width, height, min_confidence):
    lines = []
    for d in detections:
        name = DETECTOR_TO_CLASS.get(d["label"])
        if name is None or d["confidence"] < min_confidence:
            continue
        line = yolo_line(CLASS_NAMES.index(name), d["bbox"], width, height)
        if line:
            lines.append(line)
    return lines


def load_rows(path, entries_by_video):
    path = Path(path)
    report = json.loads(path.with_suffix(".json").read_text(encoding="utf-8-sig"))
    video_id = report.get("video_id")
    entries = entries_by_video.get(video_id)
    if entries is None:
        return None, None
    if report.get("status") != "complete" or report.get("source_sha256") != entries[0]["source_sha256"]:
        raise ValueError(f"Detector run for {video_id} does not match the training frames' source video")
    rows = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["frame_id"]] = row
    return video_id, rows


def run(training_dir, detection_paths, min_confidence=.25, cvat_zip=None):
    folder = Path(training_dir).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    by_video = {}
    for entry in manifest["images"]:
        by_video.setdefault(entry["video_id"], []).append(entry)
    drafts = {}
    for path in detection_paths:
        video_id, rows = load_rows(path, by_video)
        if video_id is None:
            raise ValueError(f"{path} belongs to a video that is not in this training session")
        for entry in by_video[video_id]:
            row = rows.get(entry["frame_id"])
            if row is None or abs(row["t_sec"] - entry["t_sec"]) > 1e-6:
                raise ValueError(f"Detector row for {video_id} frame {entry['frame_id']} is missing or has a different time")
            drafts[entry["image"]] = draft_lines(row["detections"], entry["width"], entry["height"], min_confidence)
    out = folder / "labels_draft"
    out.mkdir(exist_ok=True)
    for image, lines in drafts.items():
        (out / (Path(image).stem + ".txt")).write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    (out / "classes.txt").write_text("".join(n + "\n" for n in CLASS_NAMES), encoding="utf-8")
    skipped = [e["image"] for e in manifest["images"] if e["image"] not in drafts]
    if cvat_zip:
        with zipfile.ZipFile(cvat_zip, "w", zipfile.ZIP_DEFLATED) as archive:   # CVAT "YOLO 1.1" layout
            archive.writestr("obj.names", "".join(n + "\n" for n in CLASS_NAMES))
            archive.writestr("obj.data", f"classes = {len(CLASS_NAMES)}\ntrain = data/train.txt\nnames = data/obj.names\nbackup = backup/\n")
            archive.writestr("train.txt", "".join(f"data/obj_train_data/{Path(i).name}\n" for i in drafts))
            for image, lines in drafts.items():
                archive.writestr(f"obj_train_data/{Path(image).stem}.txt", "".join(l + "\n" for l in lines))
    return {"drafts": len(drafts), "images_without_detector_output": len(skipped),
            "boxes": sum(len(v) for v in drafts.values()), "folder": str(out)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-dir", type=Path, required=True)
    parser.add_argument("--detections", type=Path, action="append", required=True,
                        help="detect_disc_video.py JSONL; repeat per video")
    parser.add_argument("--min-confidence", type=float, default=.25)
    parser.add_argument("--cvat-zip", type=Path, help="Also write a CVAT 'YOLO 1.1' annotation zip")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.training_dir, args.detections, args.min_confidence, args.cvat_zip), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print(f"Pre-labelling failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
