"""Detect small discs with real-frame indexing, larger inputs, and overlapping crops."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

import cv2
import numpy as np

if __package__:
    from .detect_video import load_detection_model, model_class_names, probability, draw_detection
    from .video_tools.media import Toolchain, iter_source_frames
else:
    from detect_video import load_detection_model, model_class_names, probability, draw_detection
    from video_tools.media import Toolchain, iter_source_frames

PROJECT = Path(__file__).resolve().parents[1]
LABELS = {"person", "dog", "frisbee"}


@dataclass
class Detection:
    bbox: list[float]
    confidence: float
    label: str
    origin: str


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def crop_grid(width, height, grid=2, overlap=.2):
    """Cover the entire display frame with overlapping original-pixel crops."""
    if grid not in (0, 2, 3) or not math.isfinite(overlap) or not 0 <= overlap < .5:
        raise ValueError("Grid must be 0, 2 or 3, and overlap must be in [0, 0.5)")
    if grid == 0:
        return []
    tile_w = min(width, math.ceil(width / (grid - (grid - 1) * overlap)))
    tile_h = min(height, math.ceil(height / (grid - (grid - 1) * overlap)))
    xs = sorted({round(i * (width - tile_w) / (grid - 1)) for i in range(grid)})
    ys = sorted({round(i * (height - tile_h) / (grid - 1)) for i in range(grid)})
    return [(x, y, x + tile_w, y + tile_h) for y in ys for x in xs]


def convert_boxes(result, names, frame_size, offset=(0, 0), origin="full"):
    width, height = frame_size
    values = []
    for box in result.boxes:
        label = names.get(int(box.cls[0]), "").lower()
        if label not in LABELS:
            continue
        raw = box.xyxy[0].tolist()
        bbox = [max(0., min(float(width), float(raw[i]) + offset[0])) if i % 2 == 0
                else max(0., min(float(height), float(raw[i]) + offset[1])) for i in range(4)]
        if bbox[0] < bbox[2] and bbox[1] < bbox[3]:
            values.append(Detection(bbox, float(box.conf[0]), label, origin))
    return values


def merge_discs(detections, iou=.5):
    """Merge crop/full duplicates; retain distinct discs, including held discs."""
    discs = [d for d in detections if d.label == "frisbee"]
    others = [d for d in detections if d.label != "frisbee"]
    if not discs:
        return others
    rects = [[d.bbox[0], d.bbox[1], d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]] for d in discs]
    indices = cv2.dnn.NMSBoxes(rects, [d.confidence for d in discs], 0., iou)
    return others + [discs[int(i)] for i in np.asarray(indices).reshape(-1)]


def detect_frame(model, frame, names, *, imgsz=1280, confidence=.25,
                 disc_confidence=.25, grid=2, tile_imgsz=960, overlap=.2, device="cpu"):
    height, width = frame.shape[:2]
    relevant = [k for k, name in names.items() if name.lower() in LABELS]
    disc_ids = [k for k, name in names.items() if name.lower() == "frisbee"]
    if not relevant or not disc_ids:
        raise ValueError("The model must expose the COCO frisbee class and relevant target classes")
    predictions = model.predict(source=frame, imgsz=imgsz, conf=min(confidence, disc_confidence),
                                classes=relevant, device=device, verbose=False)[0]
    detections = convert_boxes(predictions, names, (width, height))
    for x1, y1, x2, y2 in crop_grid(width, height, grid, overlap):
        predictions = model.predict(source=frame[y1:y2, x1:x2], imgsz=tile_imgsz,
                                    conf=disc_confidence, classes=disc_ids, device=device, verbose=False)[0]
        detections.extend(convert_boxes(predictions, names, (width, height), (x1, y1), "tile"))
    detections = [d for d in detections if d.confidence >= (disc_confidence if d.label == "frisbee" else confidence)]
    return merge_discs(detections) if grid else detections


def load_source(pack, source, start=0., end=None):
    if not math.isfinite(start) or start < 0 or end is not None and (not math.isfinite(end) or end <= start):
        raise ValueError("Require 0 <= start < end, with finite times")
    pack = Path(pack).resolve()
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    matches = [v for v in manifest["videos"] if Path(v["source"]).resolve() == Path(source).resolve()]
    if len(matches) != 1 or matches[0]["status"] != "complete":
        raise ValueError("Prepare this video in the supplied packet before detection")
    video = matches[0]
    if sha256(source) != video["source_sha256"]:
        raise ValueError("Source content changed; prepare the packet again")
    path = (pack / video["paths"]["frame_index"]).resolve()
    if not path.is_relative_to(pack):
        raise ValueError("Frame index escapes the packet")
    index = json.loads(path.read_text(encoding="utf-8"))
    if len(index) != video["frames_count"] or [r["frame_id"] for r in index] != list(range(len(index))):
        raise ValueError("Invalid full source frame index")
    end = video["duration"] + .000001 if end is None else end
    if start > index[-1]["t_sec"] or end > video["duration"] + .05:
        raise ValueError("Requested time window is outside the indexed source")
    frames = [r for r in index if start <= r["t_sec"] < end]
    if not frames:
        raise ValueError("No source frames in the requested window")
    return video, frames


def run(args):
    source = args.video.resolve()
    video, frames = load_source(args.pack, source, args.start, args.end)
    output = (args.output or Path("outputs") / f"{source.stem}_disc_{args.mode}.mp4").resolve()
    if output.suffix.lower() != ".mp4" or output.is_relative_to(source.parent):
        raise ValueError("Output must be an MP4 outside the read-only source directory")
    if output.is_relative_to((PROJECT / "sources").resolve()):
        raise ValueError("Output cannot be inside synced sources/")
    sizes = args.imgsz or (640 if args.mode == "baseline" else 1280)
    grid = args.disc_grid if args.disc_grid is not None else (0 if args.mode == "baseline" else 2)
    settings = dict(imgsz=sizes, confidence=args.confidence, disc_confidence=args.disc_confidence,
                    grid=grid, tile_imgsz=args.tile_imgsz, overlap=args.overlap, device=args.device)
    crop_grid(video["width"], video["height"], grid, args.overlap)
    import torch
    torch.set_num_threads(args.cpu_threads)
    if not Path(args.model).is_file():
        raise ValueError("A local model weights file is required; this command does not download weights")
    model = load_detection_model(args.model)
    names = model_class_names(model)
    tools = Toolchain.discover(args.ffmpeg_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    temp_video = output.with_name(f".{output.stem}-{run_id}.mp4")
    result_path, report_path = output.with_suffix(".jsonl"), output.with_suffix(".json")
    temp_results = output.with_name(f".{output.stem}-{run_id}.jsonl")
    temp_report = output.with_name(f".{output.stem}-{run_id}.json")
    fps = video["metadata"]["avg_frame_rate"]
    if not fps or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Positive nominal playback frame rate required")
    writer = cv2.VideoWriter(str(temp_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (video["width"], video["height"]))
    if not writer.isOpened():
        writer.release()
        raise RuntimeError("Cannot create annotated output")
    counts = {"processed_frames": 0, "dog_frames": 0, "disc_frames": 0, "person_frames": 0}
    started = time.perf_counter()
    try:
        with temp_results.open("w", encoding="utf-8") as handle:
            for record, frame in iter_source_frames(source, frames, video["metadata"], tools):
                detections = detect_frame(model, frame, names, **settings)
                labels = {d.label for d in detections}
                for key, label in (("dog_frames", "dog"), ("disc_frames", "frisbee"), ("person_frames", "person")):
                    counts[key] += label in labels
                counts["processed_frames"] += 1
                row = {"video_id": video["id"], **record, "detections": [
                    {"label": "disc" if d.label == "frisbee" else d.label, "bbox": d.bbox,
                     "confidence": d.confidence, "origin": d.origin} for d in detections]}
                handle.write(json.dumps(row, allow_nan=False) + "\n")
                for d in detections:
                    draw_detection(frame, (*[round(v) for v in d.bbox], d.confidence, d.label))
                cv2.putText(frame, f"{args.mode} | source frame {record['frame_id']} | {record['t_sec']:.3f}s",
                            (20, 35), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
                writer.write(frame)
                if counts["processed_frames"] % 120 == 0:
                    print(f"Processed {counts['processed_frames']}/{len(frames)} source frames; disc frames {counts['disc_frames']}", flush=True)
        writer.release()
        if sha256(source) != video["source_sha256"]:
            raise ValueError("Source changed during processing")
        if counts["processed_frames"] != len(frames):
            raise ValueError("Incomplete source-frame processing")
        elapsed = time.perf_counter() - started
        report = {"status": "complete", "source": str(source), "source_sha256": video["source_sha256"],
                  "video_id": video["id"], "model": args.model, "model_sha256": sha256(args.model),
                  "settings": settings, "toolchain": tools.version, "counts": counts, "processing_seconds": elapsed,
                  "first_frame": frames[0], "last_frame": frames[-1], "video": str(output), "detections": str(result_path),
                  "limitations": ["Detection presence counts are not accuracy, throw counts or catch counts.",
                                  "No temporal track IDs or interpolated detections are produced.",
                                  "MP4 uses nominal playback FPS; JSONL retains real original-frame PTS.",
                                  "Detection JSONL is not the trajectory JSONL accepted by review-results."]}
        temp_report.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temp_video, output)
        os.replace(temp_results, result_path)
        os.replace(temp_report, report_path)
        return report
    finally:
        writer.release()
        for path in (temp_video, temp_results, temp_report):
            if path.is_file():
                path.unlink()


def main():
    parser = argparse.ArgumentParser(description="Small-disc detection with real source times and optional overlapping crops")
    parser.add_argument("video", type=Path)
    parser.add_argument("--pack", type=Path, default=PROJECT / "outputs/video-analysis-pack")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=str(PROJECT / "yolo11n.pt"))
    parser.add_argument("--mode", choices=("baseline", "enhanced"), default="enhanced")
    parser.add_argument("--confidence", type=probability, default=.25)
    parser.add_argument("--disc-confidence", type=probability, default=.25)
    parser.add_argument("--imgsz", type=int)
    parser.add_argument("--disc-grid", type=int, choices=(0, 2, 3))
    parser.add_argument("--tile-imgsz", type=int, default=960)
    parser.add_argument("--overlap", type=float, default=.2)
    parser.add_argument("--start", type=float, default=0.)
    parser.add_argument("--end", type=float)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ffmpeg-dir", type=Path)
    args = parser.parse_args()
    if args.cpu_threads < 1 or args.tile_imgsz < 32 or args.imgsz is not None and args.imgsz < 32:
        parser.error("CPU threads must be positive and image sizes at least 32")
    try:
        result = run(args)
        print(json.dumps({key: result[key] for key in ("status", "counts", "processing_seconds", "video", "detections", "settings")}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Detection failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
