"""Build an Ultralytics YOLO dataset (train/val/test) from reviewed labels, split by recording session.

Frames from one recording are strongly correlated, and the front and side views of the
same throw describe the same event. Splitting therefore happens per SESSION, never per
frame. Optional 2x2 tiles reproduce the overlapping crops the detector uses at inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
CLASS_NAMES = ("person", "dog", "frisbee")
SPLITS = ("train", "val", "test")


def _rename_with_retry(source, target, attempts=12, delay=1.0):
    """Move a finished staging folder into place.

    Windows can lock a freshly written folder (antivirus, indexer, Explorer), which makes a directory
    rename fail with WinError 5. Retry briefly, then fall back to copying the files and removing the staging copy.
    """
    import time
    for attempt in range(attempts):
        try:
            Path(source).rename(target)
            return
        except PermissionError:
            time.sleep(delay)
    if Path(target).exists():
        raise FileExistsError(f"Output already exists: {target}")
    shutil.copytree(source, target)
    shutil.rmtree(source, ignore_errors=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_label_file(path, class_count=len(CLASS_NAMES)):
    """Return [(class_id, xc, yc, w, h)]; raise ValueError on anything malformed."""
    boxes = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{Path(path).name}:{number}: expected 5 values (class x y w h), got {len(parts)}")
        try:
            class_id = int(parts[0])
            values = [float(v) for v in parts[1:]]
        except ValueError as exc:
            raise ValueError(f"{Path(path).name}:{number}: non-numeric value") from exc
        if not 0 <= class_id < class_count:
            raise ValueError(f"{Path(path).name}:{number}: class {class_id} is not one of {list(CLASS_NAMES)}")
        xc, yc, w, h = values
        if not all(math.isfinite(v) for v in values) or w <= 0 or h <= 0 or \
                xc - w / 2 < -1e-6 or yc - h / 2 < -1e-6 or xc + w / 2 > 1 + 1e-6 or yc + h / 2 > 1 + 1e-6:
            raise ValueError(f"{Path(path).name}:{number}: box is not inside the image")
        boxes.append((class_id, xc, yc, w, h))
    return boxes


def assign_splits(groups, val_fraction=.15, test_fraction=.15, seed=0):
    """Map each group to a split. Needs at least 3 groups so every split is non-empty."""
    groups = sorted(set(groups))
    if len(groups) < 3:
        raise ValueError(f"Need at least 3 sessions for a leak-free split, found {len(groups)} "
                         "(use --allow-time-block-split for a clearly labelled, leakier fallback)")
    shuffled = groups[:]
    random.Random(seed).shuffle(shuffled)
    n_test = max(1, round(len(groups) * test_fraction))
    n_val = max(1, round(len(groups) * val_fraction))
    if n_test + n_val >= len(groups):
        n_test = n_val = 1
    result = {g: "test" for g in shuffled[:n_test]}
    result.update({g: "val" for g in shuffled[n_test:n_test + n_val]})
    result.update({g: "train" for g in shuffled[n_test + n_val:]})
    return result


def assign_time_blocks(entries, block_sec=20., val_fraction=.15, test_fraction=.15, seed=0):
    """Fallback: split each video's timeline into blocks. Neighbouring blocks and the other
    camera's view of the same throw can still resemble each other, so metrics are optimistic."""
    keys = sorted({(e["session"], e["video_id"], int(e["t_sec"] // block_sec)) for e in entries})
    if len(keys) < 3:
        raise ValueError("Not enough time blocks for a split; collect more footage or lower --block-sec")
    shuffled = keys[:]
    random.Random(seed).shuffle(shuffled)
    n_test = max(1, round(len(keys) * test_fraction))
    n_val = max(1, round(len(keys) * val_fraction))
    result = {k: "test" for k in shuffled[:n_test]}
    result.update({k: "val" for k in shuffled[n_test:n_test + n_val]})
    result.update({k: "train" for k in shuffled[n_test + n_val:]})
    return result


def tile_labels(boxes, width, height, tile, min_visible=.6):
    """Clip normalized full-frame boxes to a pixel tile (x1, y1, x2, y2); drop mostly-cut boxes."""
    x1, y1, x2, y2 = tile
    tw, th = x2 - x1, y2 - y1
    out = []
    for class_id, xc, yc, w, h in boxes:
        bx1, by1, bx2, by2 = (xc - w / 2) * width, (yc - h / 2) * height, (xc + w / 2) * width, (yc + h / 2) * height
        cx1, cy1, cx2, cy2 = max(bx1, x1), max(by1, y1), min(bx2, x2), min(by2, y2)
        if cx2 <= cx1 or cy2 <= cy1:
            continue
        if (cx2 - cx1) * (cy2 - cy1) < min_visible * (bx2 - bx1) * (by2 - by1):
            continue
        out.append((class_id, ((cx1 + cx2) / 2 - x1) / tw, ((cy1 + cy2) / 2 - y1) / th,
                    (cx2 - cx1) / tw, (cy2 - cy1) / th))
    return out


def fmt(box):
    return f"{box[0]} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f} {box[4]:.6f}\n"


def yaml_text(output_dir, yaml_dir):
    rel = lambda split: Path(os.path.relpath(Path(output_dir) / "images" / split, yaml_dir)).as_posix()
    names = "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASS_NAMES))
    return ("# Generated by cv/make_dataset.py. Paths are relative to this file.\n"
            f"train: {rel('train')}\nval: {rel('val')}\ntest: {rel('test')}\nnames:\n{names}")


def build(training_dirs, output_dir, yaml_path, seed=0, val_fraction=.15, test_fraction=.15, tiles=False,
          tile_grid=2, tile_overlap=.2, allow_time_block_split=False, block_sec=20., strict=False,
          labels_subdir="labels"):
    if labels_subdir == "labels_draft":
        raise ValueError("Refusing to build from labels_draft: drafts must be human-reviewed into 'labels' first")
    output, yaml_path = Path(output_dir).resolve(), Path(yaml_path).resolve()
    if output.exists():
        raise ValueError(f"Dataset directory already exists: {output}. Build into a new directory.")
    items, missing, sessions = [], [], set()
    for training in training_dirs:
        folder = Path(training).resolve()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if manifest["session"] in sessions:
            raise ValueError(f"Session listed twice: {manifest['session']}")
        sessions.add(manifest["session"])
        for entry in manifest["images"]:
            label = folder / labels_subdir / (Path(entry["image"]).stem + ".txt")
            image = folder / entry["image"]
            if not image.is_file():
                raise ValueError(f"Image missing: {image}")
            if not label.is_file():
                missing.append(str(label))
                continue
            items.append({**entry, "image_path": image, "boxes": parse_label_file(label),
                          "label_sha256": sha256(label), "manifest_sha256": sha256(folder / "manifest.json")})
    if missing and strict:
        raise ValueError(f"{len(missing)} images have no reviewed label file (first: {missing[0]})")
    if not items:
        raise ValueError("No reviewed labels found")
    if allow_time_block_split and len(sessions) < 3:
        blocks = assign_time_blocks(items, block_sec, val_fraction, test_fraction, seed)
        split_of = lambda e: blocks[(e["session"], e["video_id"], int(e["t_sec"] // block_sec))]
        method = "time_blocks_LEAKY"
    else:
        groups = assign_splits([e["session"] for e in items], val_fraction, test_fraction, seed)
        split_of = lambda e: groups[e["session"]]
        method = "by_session"
    staging = output.parent / f".{output.name}-building"
    if staging.exists():
        shutil.rmtree(staging)
    for split in SPLITS:
        (staging / "images" / split).mkdir(parents=True)
        (staging / "labels" / split).mkdir(parents=True)
    if tiles:
        if __package__:
            from .detect_disc_video import crop_grid
        else:
            from detect_disc_video import crop_grid
    counts = {s: {"images": 0, "tiles": 0, "instances": {n: 0 for n in CLASS_NAMES}} for s in SPLITS}
    try:
        for item in items:
            split = split_of(item)
            stem = f"{item['session']}__{Path(item['image']).stem}"
            shutil.copy2(item["image_path"], staging / "images" / split / f"{stem}.jpg")
            (staging / "labels" / split / f"{stem}.txt").write_text("".join(fmt(b) for b in item["boxes"]), encoding="utf-8")
            counts[split]["images"] += 1
            for b in item["boxes"]:
                counts[split]["instances"][CLASS_NAMES[b[0]]] += 1
            if tiles:
                import cv2
                frame = cv2.imread(str(item["image_path"]))
                if frame is None or frame.shape[:2] != (item["height"], item["width"]):
                    raise ValueError(f"Image size differs from its manifest: {item['image_path']}")
                for number, tile in enumerate(crop_grid(item["width"], item["height"], tile_grid, tile_overlap)):
                    boxes = tile_labels(item["boxes"], item["width"], item["height"], tile)
                    x1, y1, x2, y2 = tile
                    name = f"{stem}__t{number}"
                    cv2.imwrite(str(staging / "images" / split / f"{name}.jpg"), frame[y1:y2, x1:x2],
                                [cv2.IMWRITE_JPEG_QUALITY, 95])
                    (staging / "labels" / split / f"{name}.txt").write_text("".join(fmt(b) for b in boxes), encoding="utf-8")
                    counts[split]["tiles"] += 1
                    for b in boxes:
                        counts[split]["instances"][CLASS_NAMES[b[0]]] += 1
        warnings = []
        for split in ("val", "test"):
            for name in CLASS_NAMES:
                if counts[split]["instances"][name] == 0:
                    warnings.append(f"{split} split has no '{name}' instances; its metrics for that class are meaningless")
        if method != "by_session":
            warnings.append("Time-block split: val/test frames can resemble training frames, so metrics are optimistic")
        report = {"schema_version": 1, "split_method": method, "seed": seed, "sessions": sorted(sessions),
                  "session_split": {s: sorted({split_of(e) for e in items if e["session"] == s}) for s in sorted(sessions)},
                  "tiles": tiles, "counts": counts, "images_without_reviewed_labels": len(missing),
                  "inputs": sorted({(i["manifest_sha256"]) for i in items}), "warnings": warnings}
        (staging / "dataset-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        _rename_with_retry(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml_text(output, yaml_path.parent), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-dir", type=Path, action="append", required=True,
                        help="Session folder from build_training_frames.py (repeat per session)")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "data" / "dataset")
    parser.add_argument("--yaml", type=Path, default=PROJECT / "data" / "dataset.yaml")
    parser.add_argument("--labels-subdir", default="labels", help="Reviewed labels folder inside each session (default: labels)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--val-fraction", type=float, default=.15)
    parser.add_argument("--test-fraction", type=float, default=.15)
    parser.add_argument("--tiles", action="store_true", help="Also export 2x2 overlapping tiles matching inference")
    parser.add_argument("--allow-time-block-split", action="store_true",
                        help="With fewer than 3 sessions, split by time blocks (leaky; metrics are optimistic)")
    parser.add_argument("--block-sec", type=float, default=20.)
    parser.add_argument("--strict", action="store_true", help="Fail if any image lacks a reviewed label file")
    args = parser.parse_args()
    try:
        report = build(args.training_dir, args.output_dir, args.yaml, args.seed, args.val_fraction, args.test_fraction,
                       args.tiles, allow_time_block_split=args.allow_time_block_split, block_sec=args.block_sec,
                       strict=args.strict, labels_subdir=args.labels_subdir)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Dataset build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
