"""Track a single primary dog from saved detections; render original frames."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import asdict
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import cv2

if __package__:
    from .dog_tracker import DogTracker, TrackingSettings, center, contract_row
    from .detect_disc_video import load_source, sha256
    from .video_tools.media import Toolchain, iter_source_frames
    from .video_tools.review import validate_results
else:
    from dog_tracker import DogTracker, TrackingSettings, center, contract_row
    from detect_disc_video import load_source, sha256
    from video_tools.media import Toolchain, iter_source_frames
    from video_tools.review import validate_results

PROJECT = Path(__file__).resolve().parents[1]
VERSION = 1


def read_json(path):
    def constant(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=constant, object_pairs_hook=unique)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_detections(path, pack):
    path = Path(path).resolve()
    report = read_json(path.with_suffix(".json"))
    if report.get("status") != "complete":
        raise ValueError("Only complete detector runs are accepted")
    video, index = load_source(pack, Path(report["source"]))
    if report.get("video_id") != video["id"] or report.get("source_sha256") != video["source_sha256"]:
        raise ValueError("Detector provenance does not match the prepared source")
    first, last = report["first_frame"]["frame_id"], report["last_frame"]["frame_id"]
    if type(first) is not int or type(last) is not int or not 0 <= first <= last < len(index):
        raise ValueError("Invalid detector frame range")
    expected = index[first:last + 1]
    rows = [read_json_line(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(rows) != len(expected) or len(rows) != report["counts"]["processed_frames"]:
        raise ValueError("Detector row count does not match the declared continuous frame range")
    counts = Counter()
    for row, record in zip(rows, expected):
        if row.get("video_id") != video["id"] or type(row.get("frame_id")) is not int or row["frame_id"] != record["frame_id"]:
            raise ValueError("Detector source frame identity mismatch")
        for key in ("t_sec", "pts_sec"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - record[key]) > .000001:
                raise ValueError("Detector time differs from the original frame index")
        if row.get("timestamp_source") != record["timestamp_source"] or not isinstance(row.get("detections"), list):
            raise ValueError("Invalid detection record")
        labels = set()
        for detection in row["detections"]:
            label, box, conf = detection.get("label"), detection.get("bbox"), detection.get("confidence")
            if label not in {"dog", "disc", "person"} or not isinstance(box, list) or len(box) != 4:
                raise ValueError("Invalid class or box")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
                raise ValueError("Invalid box coordinates")
            if not 0 <= box[0] < box[2] <= video["width"] or not 0 <= box[1] < box[3] <= video["height"]:
                raise ValueError("Detection is outside the oriented source frame")
            if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
                raise ValueError("Invalid confidence")
            labels.add(label)
        counts.update(f"{label}_frames" for label in labels)
    for label in ("dog", "disc", "person"):
        if counts[f"{label}_frames"] != report["counts"][f"{label}_frames"]:
            raise ValueError("Detector observation counts disagree with JSONL")
    for name, record in (("first_frame", expected[0]), ("last_frame", expected[-1])):
        if report[name] != record:
            raise ValueError("Detector summary endpoints disagree with source index")
    return video, expected, rows, report


def read_json_line(line):
    # Reuse the strict parser without needing temporary files.
    def constant(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result
    return json.loads(line, parse_constant=constant, object_pairs_hook=unique)


def draw_box(frame, box, color, dashed=False):
    x1, y1, x2, y2 = map(round, box)
    thickness = max(2, frame.shape[1] // 700)
    if not dashed:
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        return
    for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        distance = math.dist(a, b)
        if distance:
            for start in range(0, math.ceil(distance), 18):
                p = tuple(round(a[i] + (b[i] - a[i]) * start / distance) for i in range(2))
                q = tuple(round(a[i] + (b[i] - a[i]) * min(start + 9, distance) / distance) for i in range(2))
                cv2.line(frame, p, q, color, thickness)


def annotate(frame, record, observation, trail):
    now, identity = record["t_sec"], observation["track_id"]
    trail.append((now, identity, center(observation["bbox"]) if observation["bbox"] else None))
    while trail and now - trail[0][0] > 2:
        trail.popleft()
    for a, b in zip(trail, list(trail)[1:]):
        if a[1] == b[1] and a[2] is not None and b[2] is not None:
            cv2.line(frame, tuple(map(round, a[2])), tuple(map(round, b[2])), (0, 220, 0), 2)
    box = observation["bbox"] or observation["prediction_bbox"] or observation["tentative_bbox"]
    state = observation["state"]
    color = (0, 220, 0) if state == "detected" else (0, 210, 255) if state == "predicted" else (160, 160, 160)
    if box:
        draw_box(frame, box, color, state == "predicted")
    scale = max(.7, frame.shape[1] / 1600)
    text = f"{identity or 'unassigned'} | {state.upper()} | frame {record['frame_id']} | source {now:.3f}s"
    if state == "predicted":
        text += " | NO MEASUREMENT"
    cv2.rectangle(frame, (0, 0), (min(frame.shape[1], round(1050 * scale)), round(48 * scale)), (25, 25, 25), -1)
    cv2.putText(frame, text, (round(8 * scale), round(30 * scale)), cv2.FONT_HERSHEY_SIMPLEX, scale * .65, color, max(1, round(scale * 2)))
    return frame


def run(detections, pack, output_dir, settings=None, ffmpeg_dir=None, start=0., end=None):
    started = time.perf_counter()
    settings = settings or TrackingSettings()
    detections, pack, output = Path(detections).resolve(), Path(pack).resolve(), Path(output_dir).resolve()
    video, records, detector_rows, detector_report = load_detections(detections, pack)
    source = Path(video["source"]).resolve()
    if output.is_relative_to(source.parent) or output.is_relative_to((PROJECT / "sources").resolve()) or output == detections.parent or output == pack or output.is_relative_to(pack):
        raise ValueError("Choose a separate output directory outside source footage and the prepared packet")
    if not math.isfinite(start) or start < 0 or end is not None and (not math.isfinite(end) or end <= start):
        raise ValueError("Require finite 0 <= start < end")
    selected = [(r, d) for r, d in zip(records, detector_rows) if r["t_sec"] >= start and (end is None or r["t_sec"] < end)]
    if not selected:
        raise ValueError("No detections in requested window")
    records, detector_rows = map(list, zip(*selected))
    tools = Toolchain.discover(ffmpeg_dir)
    code_files = [Path(__file__), Path(__file__).with_name("dog_tracker.py"), Path(__file__).with_name("detect_disc_video.py"), Path(__file__).parent / "video_tools" / "media.py"]
    signature = {"version": VERSION, "source_sha256": video["source_sha256"], "detections_sha256": sha256(detections),
                 "detector_report_sha256": sha256(detections.with_suffix(".json")), "settings": asdict(settings),
                 "first_frame": records[0], "last_frame": records[-1], "toolchain": tools.version,
                 "code": {str(p.relative_to(Path(__file__).parent)): sha256(p) for p in code_files}, "opencv": cv2.__version__}
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    if output.exists():
        summary = read_json(output / "summary.json")
        if summary.get("status") != "complete" or summary.get("cache_key") != key:
            raise ValueError("Output already exists with different settings/input; use a new output directory")
        for name, digest in summary["artifact_sha256"].items():
            target = (output / name).resolve()
            if not target.is_relative_to(output) or sha256(target) != digest:
                raise ValueError("Cached output changed; choose a new directory to regenerate")
        print(f"Verified cache: {output}", flush=True)
        return summary
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.parent / f".dog-tracking-{uuid.uuid4().hex}"
    temp.mkdir()
    writer = None
    try:
        tracker = DogTracker(video["width"], video["height"], settings)
        observations, tracks = [], []
        compute_started = time.perf_counter()
        for record, row in zip(records, detector_rows):
            observation = tracker.update(record["t_sec"], row["detections"])
            observations.append({**record, **observation})
            tracks.append(contract_row(video["id"], record, observation))
        compute_seconds = time.perf_counter() - compute_started
        manifest = read_json(pack / "manifest.json")
        full_index = read_json(pack / video["paths"]["frame_index"])
        validate_results(tracks, manifest, {video["id"]: full_index})
        for name, rows in (("tracks.jsonl", tracks), ("states.jsonl", observations)):
            (temp / name).write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows), encoding="utf-8")
        with (temp / "trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
            csv_writer = csv.writer(handle)
            csv_writer.writerow(["video_id", "frame_id", "t_sec", "pts_sec", "track_id", "state", "measured_x_px", "measured_y_px", "predicted_x_px", "predicted_y_px", "confidence"])
            for row in observations:
                csv_writer.writerow([video["id"], row["frame_id"], row["t_sec"], row["pts_sec"], row["track_id"] or "", row["state"],
                                     *(center(row["bbox"]) if row["bbox"] else ["", ""]),
                                     *(center(row["prediction_bbox"]) if row["prediction_bbox"] else ["", ""]),
                                     row["confidence"] if row["confidence"] is not None else ""])
        fps = video["metadata"]["avg_frame_rate"]
        if not fps or not math.isfinite(fps) or fps <= 0:
            raise ValueError("Positive nominal preview frame rate required")
        writer = cv2.VideoWriter(str(temp / "tracked.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (video["width"], video["height"]))
        if not writer.isOpened():
            raise RuntimeError("Cannot open tracking video writer")
        trail, decoded = deque(), 0
        still_ids = {0, len(records) // 2, len(records) - 1}
        # Also retain the first short prediction and the first long loss, with
        # their immediate neighbours, for a bounded initial visual audit.
        for wanted in ("predicted", "lost"):
            item = next((i for i, r in enumerate(observations) if r["state"] == wanted), None)
            if item is not None:
                still_ids.update({max(0, item - 1), item, min(len(records) - 1, item + 1)})
        for i, (record, frame) in enumerate(iter_source_frames(source, records, video["metadata"], tools)):
            annotated = annotate(frame, record, observations[i], trail)
            writer.write(annotated)
            if i in still_ids:
                if not cv2.imwrite(str(temp / f"frame-{record['frame_id']:06d}.jpg"), annotated):
                    raise RuntimeError("Cannot save tracking audit image")
            decoded += 1
            if decoded % 300 == 0:
                print(f"{video['id']}: rendered {decoded}/{len(records)} source frames", flush=True)
        writer.release()
        writer = None
        probe = subprocess.run([tools.ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_read_frames", "-of", "json", str(temp / "tracked.mp4")], capture_output=True, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        if decoded != len(records) or int(stream["nb_read_frames"]) != decoded or (stream["width"], stream["height"]) != (video["width"], video["height"]):
            raise RuntimeError("Tracking replay failed frame-count/dimension verification")
        if sha256(source) != video["source_sha256"] or sha256(detections) != signature["detections_sha256"] or sha256(detections.with_suffix(".json")) != signature["detector_report_sha256"]:
            raise ValueError("Source or detector input changed during tracking")
        states = Counter(row["state"] for row in observations)
        gaps, gap_start = [], None
        for i, row in enumerate(observations):
            if row["state"] != "detected" and gap_start is None:
                gap_start = i
            if gap_start is not None and (row["state"] == "detected" or i == len(observations) - 1):
                last = i - 1 if row["state"] == "detected" else i
                gaps.append({"start_frame": records[gap_start]["frame_id"], "end_frame": records[last]["frame_id"],
                             "start_sec": records[gap_start]["t_sec"], "end_sec": records[last]["t_sec"], "frames": last - gap_start + 1})
                gap_start = None
        summary = {"status": "complete", "video_id": video["id"], "source": str(source), "cache_key": key,
                   "provenance": signature, "processed_frames": decoded, "raw_dog_frames": sum(any(d["label"] == "dog" for d in r["detections"]) for r in detector_rows),
                   "states": dict(states), "track_count": tracker.track_count, "reacquisitions": sum(r["reacquired"] for r in observations),
                   "retired_tracks": sum(r["retired_track_id"] is not None for r in observations),
                   "rejection_reasons": dict(Counter(r["reason"] for r in observations if r["reason"])),
                   "missing_windows": sorted(gaps, key=lambda g: g["frames"], reverse=True),
                   "tracking_compute_seconds": compute_seconds, "processing_seconds": time.perf_counter() - started,
                   "validated": {"source_content_unchanged": True, "source_timestamp_index": True, "review_contract": True, "output_frame_count": decoded},
                   "limitations": ["Single primary dog; no appearance re-identification or camera-motion compensation.",
                                   "Green = accepted measurement; dashed yellow = bounded prediction, never an observed detection.",
                                   "Long absence can end an ID; different IDs may represent the same dog.",
                                   "Counts describe tracker behaviour, not recognition accuracy.",
                                   "Pixel coordinates in oriented source dimensions; no physical distance or speed calibration.",
                                   "MP4 uses nominal playback FPS without audio; JSONL and CSV retain true source timestamps.",
                                   "dog-unassigned is a placeholder for frames before confirmation; not an established identity."]}
        summary["artifact_sha256"] = {p.name: sha256(p) for p in sorted(temp.iterdir()) if p.is_file()}
        write_json(temp / "summary.json", summary)
        temp.rename(output)
        print(json.dumps({"output": str(output), "frames": decoded, "states": dict(states), "tracks": tracker.track_count}, ensure_ascii=False), flush=True)
        return summary
    finally:
        if writer is not None:
            writer.release()
        # Only the exact staging directory created by this invocation is removed.
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != output.parent or not resolved.name.startswith(".dog-tracking-"):
                raise RuntimeError("Unexpected staging path; refusing cleanup")
            shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detections", required=True, type=Path)
    parser.add_argument("--pack", type=Path, default=PROJECT / "outputs" / "video-analysis-pack")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--start", type=float, default=0.)
    parser.add_argument("--end", type=float)
    parser.add_argument("--prediction-seconds", type=float, default=.25)
    parser.add_argument("--identity-gap-seconds", type=float, default=.75)
    parser.add_argument("--confirm-samples", type=int, default=3)
    parser.add_argument("--confidence", type=float, default=.25)
    parser.add_argument("--ffmpeg-dir", type=Path)
    args = parser.parse_args()
    try:
        settings = TrackingSettings(confirm_samples=args.confirm_samples, prediction_sec=args.prediction_seconds,
                                    identity_gap_sec=args.identity_gap_seconds, confidence=args.confidence)
        run(args.detections, args.pack, args.output_dir, settings, args.ffmpeg_dir, args.start, args.end)
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Tracking failed: {exc}\n")


if __name__ == "__main__":
    main()
