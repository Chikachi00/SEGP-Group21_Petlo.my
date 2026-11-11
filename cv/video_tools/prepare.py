"""Build a bounded, timestamped video review package from read-only source videos."""
from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from .media import MediaError, Toolchain, extract_frames, probe_video, scan_video


LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
PREPARE_VERSION = 1
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts"}
PARAMETERS = {"prepare_version": PREPARE_VERSION, "sparse_interval_sec": 1.0,
              "action_overview_count": 6, "portrait_overview_count": 4, "context_overview_count": 4,
              "candidate_count": 2, "candidate_half_width_sec": 1.0,
              "candidate_motion_smoothing_sec": 0.25, "candidate_sample_fps": 10.0, "max_side": 1280}


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _classify(source: Path) -> tuple[str, str, int]:
    name = source.stem.casefold()
    role = "context" if "setup" in name else "action"
    camera = "tripod" if "tripod" in name else "handheld" if "handheld" in name else "unknown"
    overview_count = 4 if role == "context" or "portrait" in name else 6
    return role, camera, overview_count


def _sample_frames(frames: list[dict], start: float, end: float, interval: float,
                   *, include_last: bool = True) -> list[dict]:
    """Choose the first real frame at/after each target; never manufacture frames."""
    times = [frame["t_sec"] for frame in frames]
    chosen = {}
    steps = max(0, int(math.floor((end - start) / interval + 1e-8)))
    for step in range(steps + 1):
        index = bisect.bisect_left(times, start + step * interval - 1e-9)
        if index < len(frames) and times[index] <= end + 1e-9:
            chosen[frames[index]["frame_id"]] = frames[index]
    if include_last:
        index = bisect.bisect_right(times, end + 1e-9) - 1
        if index >= 0 and times[index] >= start - 1e-9:
            chosen[frames[index]["frame_id"]] = frames[index]
    return [chosen[key] for key in sorted(chosen)]


def _overview_frames(pool: list[dict], requested: int) -> list[dict]:
    count = min(requested, len(pool))
    if count == len(pool):
        return list(pool)
    times = [frame["t_sec"] for frame in pool]
    selected = {0, len(pool) - 1}
    targets = [times[0] + (times[-1] - times[0]) * index / (count - 1) for index in range(count)]
    for target in targets[1:-1]:
        selected.add(min(range(len(pool)), key=lambda index: (abs(times[index] - target), index)))
    if len(selected) < count:
        remaining = [index for index in range(len(pool)) if index not in selected]
        remaining.sort(key=lambda index: (-min(abs(times[index] - times[other]) for other in selected), index))
        selected.update(remaining[:count - len(selected)])
    return [pool[index] for index in sorted(selected)]


def _candidate_windows(frames: list[dict], motion: list[dict], role: str) -> list[dict]:
    if role == "context" or len(frames) < 2:
        return []
    times = [row["t_sec"] for row in motion]
    prefix = [0.0]
    for row in motion:
        prefix.append(prefix[-1] + row["motion_score"])
    half_smoothing = PARAMETERS["candidate_motion_smoothing_sec"] / 2
    scored = []
    for index, row in enumerate(motion):
        left = bisect.bisect_left(times, row["t_sec"] - half_smoothing)
        right = bisect.bisect_right(times, row["t_sec"] + half_smoothing)
        score = (prefix[right] - prefix[left]) / (right - left)
        if score > 0.00000001:
            scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], times[item[1]]))
    last_time = frames[-1]["t_sec"]
    windows = []
    for score, index in scored:
        center = times[index]
        start, end = max(0.0, center - 1.0), min(last_time, center + 1.0)
        if end <= start or any(start < window["end_sec"] and end > window["start_sec"] for window in windows):
            continue
        windows.append({"id": f"motion_{len(windows) + 1:02d}", "start_sec": round(start, 9),
                        "end_sec": round(end, 9), "center_sec": center,
                        "reason": "high_motion_review_candidate", "score": round(score, 9)})
        if len(windows) >= PARAMETERS["candidate_count"]:
            break
    return windows


def _font(size: int):
    from PIL import ImageFont
    candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _contact_sheet(images: list[tuple[Path, str]], destination: Path, columns: int) -> None:
    from PIL import Image, ImageDraw
    if not images:
        raise MediaError("Cannot create an overview without images")
    width, height, caption, padding = 384, 216, 44, 12
    rows = math.ceil(len(images) / columns)
    canvas = Image.new("RGB", (columns * (width + padding) + padding,
                               rows * (height + caption + padding) + padding), "#192330")
    draw = ImageDraw.Draw(canvas)
    font = _font(17)
    for index, (path, label) in enumerate(images):
        x, y = padding + index % columns * (width + padding), padding + index // columns * (height + caption + padding)
        with Image.open(path) as picture:
            thumbnail = picture.convert("RGB")
            thumbnail.thumbnail((width, height), Image.Resampling.LANCZOS)
            canvas.paste(thumbnail, (x + (width - thumbnail.width) // 2, y + (height - thumbnail.height) // 2))
        draw.text((x, y + height + 5), label, fill="white", font=font)
    canvas.save(destination, quality=90, optimize=True)


def _package_path(root: Path, directory: Path, filename: str) -> str:
    return (directory / filename).relative_to(root).as_posix()


def _safe_remove(path: Path, output_root: Path) -> None:
    resolved = path.resolve()
    root = output_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise MediaError(f"Refusing to remove a path outside the package: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _commit_video(staging: Path, destination: Path, root: Path) -> None:
    backup = destination.with_name(f".{destination.name}.backup-{uuid.uuid4().hex}")
    if destination.exists():
        destination.rename(backup)
    try:
        staging.rename(destination)
    except BaseException:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        _safe_remove(backup, root)


def _cached_video(destination: Path, key: str, root: Path) -> dict | None:
    """Reuse only a complete package whose indexes and all images still validate."""
    from PIL import Image
    try:
        record = json.loads((destination / "video.json").read_text(encoding="utf-8"))
        if record.get("status") != "complete" or record.get("cache_key") != key:
            return None
        loaded = {}
        for name in ("frame_index", "motion_index", "image_index", "candidates"):
            artifact = (root / record["paths"][name]).resolve()
            if root not in artifact.parents or not artifact.is_file():
                return None
            loaded[name] = json.loads(artifact.read_text(encoding="utf-8"))
            if not isinstance(loaded[name], list):
                return None
        if len(loaded["frame_index"]) != record["frames_count"] or len(loaded["motion_index"]) != record["frames_count"]:
            return None
        frames = loaded["frame_index"]
        if not frames:
            return None
        first_pts = frames[0]["pts_sec"]
        previous_pts = None
        for frame_id, frame in enumerate(frames):
            if (isinstance(frame["frame_id"], bool) or frame["frame_id"] != frame_id
                    or not all(math.isfinite(frame[field]) for field in ("pts_sec", "t_sec"))
                    or abs(frame["pts_sec"] - first_pts - frame["t_sec"]) > 0.00001
                    or frame["timestamp_source"] not in ("pts_time", "best_effort_timestamp_time")
                    or (previous_pts is not None and frame["pts_sec"] <= previous_pts)):
                return None
            previous_pts = frame["pts_sec"]
        for frame, motion in zip(frames, loaded["motion_index"]):
            if (motion["frame_id"] != frame["frame_id"] or motion["pts_sec"] != frame["pts_sec"]
                    or motion["t_sec"] != frame["t_sec"] or not math.isfinite(motion["motion_score"])
                    or not 0 <= motion["motion_score"] <= 1):
                return None
        if not record.get("parameters", {}).get("review_artifacts", True):
            if (loaded["image_index"] or loaded["candidates"] or record.get("overview_frame_ids") != []
                    or any(record.get(name) != 0 for name in ("candidate_count", "images_count", "overview_count"))
                    or record["paths"]["overview"] is not None):
                return None
            return record
        if not loaded["image_index"]:
            return None
        image_ids = set()
        for image in loaded["image_index"]:
            frame_id = image["frame_id"]
            if isinstance(frame_id, bool) or not isinstance(frame_id, int) or not 0 <= frame_id < len(frames):
                return None
            if frame_id in image_ids or image["pts_sec"] != frames[frame_id]["pts_sec"] or image["t_sec"] != frames[frame_id]["t_sec"]:
                return None
            image_ids.add(frame_id)
            artifact = (destination / image["path"]).resolve()
            if destination.resolve() not in artifact.parents:
                return None
            with Image.open(artifact) as picture:
                if picture.size != (image["width"], image["height"]):
                    return None
                picture.verify()
            if (image["source_width"] != record["width"] or image["source_height"] != record["height"]
                    or image["crop"] != [0, 0, record["width"], record["height"]]
                    or abs(image["scale_x"] - image["width"] / record["width"]) > 0.0000001
                    or abs(image["scale_y"] - image["height"] / record["height"]) > 0.0000001):
                return None
        if not set(record["overview_frame_ids"]).issubset(image_ids):
            return None
        for window in loaded["candidates"]:
            if (not all(math.isfinite(window[field]) for field in ("start_sec", "end_sec", "center_sec", "score"))
                    or not 0 <= window["start_sec"] < window["end_sec"] <= frames[-1]["t_sec"] + 0.00001
                    or not window["start_sec"] <= window["center_sec"] <= window["end_sec"]):
                return None
        if record["role"] == "context" and loaded["candidates"]:
            return None
        windows = loaded["candidates"]
        if any(left["start_sec"] < right["end_sec"] and left["end_sec"] > right["start_sec"]
               for index, left in enumerate(windows) for right in windows[index+1:]):
            return None
        overview_path = (root / record["paths"]["overview"]).resolve()
        if root not in overview_path.parents:
            return None
        with Image.open(overview_path) as picture:
            picture.verify()
        return record
    except (OSError, ValueError, KeyError, TypeError, SyntaxError):
        return None


def _prepare_one(source: Path, root: Path, tools: Toolchain, force: bool, review_artifacts: bool = True) -> dict:
    video_id = source.stem
    role, camera, overview_count = _classify(source)
    source_hash = _sha256(source)
    parameters = dict(PARAMETERS, role=role, camera=camera, overview_count=overview_count,
                      review_artifacts=review_artifacts)
    key = hashlib.sha256(json.dumps({"source_sha256": source_hash, "parameters": parameters,
                                    "toolversions": tools.version}, sort_keys=True).encode()).hexdigest()
    destination = root / "videos" / video_id
    if not force:
        cached = _cached_video(destination, key, root)
        if cached is not None:
            LOGGER.info("Reusing validated package: %s", source.name)
            return dict(cached, cached=True)
    LOGGER.info("Decoding and preparing: %s", source.name)
    staging = root / "videos" / f".{video_id}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    entry = {"id": video_id, "source": str(source), "source_sha256": source_hash,
             "status": "failed", "role": role, "camera": camera,
             "width": None, "height": None, "encoded_width": None, "encoded_height": None,
             "rotation": None, "duration": None, "frames_count": None,
             "paths": {"frame_index": None, "motion_index": None, "image_index": None,
                       "overview": None, "candidates": None}, "error": None,
             "warnings": [], "cache_key": key, "parameters": parameters, "cached": False}
    try:
        metadata = probe_video(source, tools)
        for field in ("width", "height", "encoded_width", "encoded_height", "rotation", "duration", "frames_count"):
            entry[field] = metadata[field]
        entry["warnings"] = list(metadata["warnings"])
        metadata, frames, motion = scan_video(source, tools)
        for field in ("width", "height", "encoded_width", "encoded_height", "rotation", "duration", "frames_count"):
            entry[field] = metadata[field]
        entry["metadata"] = metadata
        entry["warnings"] = list(metadata["warnings"])
        images, overview, windows = [], [], []
        if review_artifacts:
            sparse = _sample_frames(frames, 0.0, frames[-1]["t_sec"], PARAMETERS["sparse_interval_sec"])
            overview = _overview_frames(sparse, overview_count)
            windows = _candidate_windows(frames, motion, role)
            selected = {frame["frame_id"]: frame for frame in sparse}
            window_membership = {}
            for window in windows:
                for frame in _sample_frames(frames, window["start_sec"], window["end_sec"],
                                             1.0 / PARAMETERS["candidate_sample_fps"]):
                    selected[frame["frame_id"]] = frame
                    window_membership.setdefault(frame["frame_id"], []).append(window["id"])
            images = extract_frames(source, selected.values(), staging / "images", tools, PARAMETERS["max_side"])
            sparse_ids = {frame["frame_id"] for frame in sparse}
            overview_ids = {frame["frame_id"] for frame in overview}
            for image in images:
                image["path"] = Path(image["path"]).relative_to(staging).as_posix()
                image["kinds"] = (["sparse"] if image["frame_id"] in sparse_ids else [])
                if image["frame_id"] in overview_ids:
                    image["kinds"].append("overview")
                image["window_ids"] = window_membership.get(image["frame_id"], [])
                if image["window_ids"]:
                    image["kinds"].append("candidate")
                image["kind"] = "candidate" if image["window_ids"] else "overview" if image["frame_id"] in overview_ids else "sparse"
        _write_json(staging / "frame_index.json", frames)
        _write_json(staging / "motion_index.json", motion)
        _write_json(staging / "image_index.json", images)
        _write_json(staging / "candidate_windows.json", windows)
        if review_artifacts:
            image_by_id = {image["frame_id"]: image for image in images}
            _contact_sheet([(staging / image_by_id[frame["frame_id"]]["path"], f"{frame['t_sec']:.3f}s | frame {frame['frame_id']}")
                            for frame in overview], staging / "overview.jpg", 3 if overview_count == 6 else 2)
        entry["overview_frame_ids"] = [frame["frame_id"] for frame in overview]
        entry["candidate_count"] = len(windows)
        entry["images_count"] = len(images)
        entry["overview_count"] = len(overview)
        if review_artifacts and len(overview) < overview_count:
            entry["warnings"].append("Too few source samples for the requested overview count.")
        if review_artifacts and role == "action" and not windows:
            entry["warnings"].append("No measurable motion candidates; genuinely static frames remain valid.")
        if review_artifacts and camera == "handheld":
            entry["warnings"].append("Motion scores include camera motion; candidate windows require visual review.")
        if windows:
            entry["warnings"].append("High motion windows are review suggestions and do not establish catches or other events.")
        if _sha256(source) != source_hash:
            raise MediaError("Source video changed while preparing; rerun against an unchanged source.")
        entry["paths"] = {name: _package_path(root, destination, filename) for name, filename in
                          (("frame_index", "frame_index.json"), ("motion_index", "motion_index.json"),
                           ("image_index", "image_index.json"), ("overview", "overview.jpg"),
                           ("candidates", "candidate_windows.json"))}
        if not review_artifacts:
            entry["paths"]["overview"] = None
        entry["status"] = "complete"
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        (staging / "error.txt").write_text(entry["error"] + "\n", encoding="utf-8")
        LOGGER.warning("Failed video %s: %s", source.name, entry["error"])
    try:
        _write_json(staging / "video.json", entry)
        _commit_video(staging, destination, root)
    finally:
        if staging.exists():
            _safe_remove(staging, root)
    return entry


def prepare(source_root: str | Path, output_root: str | Path, tools: Toolchain,
            force: bool = False, *, review_artifacts: bool = True) -> dict[str, Any]:
    """Prepare every immediate video child and atomically publish manifest.json.

    Outputs may never be created inside source_root. Individual decode failures
    are represented in the manifest and do not stop the other videos.
    Disable review_artifacts for analysis-only packages: every source frame is
    still decoded and timestamp-validated, without a second JPEG extraction pass.
    """
    source = Path(source_root).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    if not source.is_dir():
        raise MediaError(f"Source video directory does not exist: {source}")
    if root == source or source in root.parents:
        raise MediaError("Package output must be outside the source video directory")
    videos = sorted((path for path in source.iterdir() if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS),
                    key=lambda path: path.name.casefold())
    if not videos:
        raise MediaError(f"No supported video files in {source}")
    ids = [path.stem.casefold() for path in videos]
    if len(set(ids)) != len(ids):
        raise MediaError("Video filename stems must be unique to create unambiguous package IDs")
    root.mkdir(parents=True, exist_ok=True)
    (root / "videos").mkdir(exist_ok=True)
    entries = [_prepare_one(path, root, tools, force, review_artifacts) for path in videos]
    manifest = {"schema_version": SCHEMA_VERSION,
                "toolchain": {"ffmpeg": tools.ffmpeg, "ffprobe": tools.ffprobe, "version": tools.version},
                "source_root": str(source), "parameters": dict(PARAMETERS, review_artifacts=review_artifacts), "videos": entries,
                "overview": None}
    combined = []
    for entry in entries:
        if entry["status"] != "complete" or not review_artifacts:
            continue
        directory = root / "videos" / entry["id"]
        images = json.loads((root / entry["paths"]["image_index"]).read_text(encoding="utf-8"))
        by_id = {image["frame_id"]: image for image in images}
        for frame_id in entry["overview_frame_ids"]:
            image = by_id[frame_id]
            label = entry["id"].replace("Landscape_Tripod_", "").replace("Portrait_Handheld", "Portrait")
            combined.append((directory / image["path"], f"{label} | {image['t_sec']:.3f}s"))
    if combined:
        temporary_overview = root / f".overview-{uuid.uuid4().hex}.jpg"
        _contact_sheet(combined, temporary_overview, 5)
        os.replace(temporary_overview, root / "overview.jpg")
        manifest["overview"] = "overview.jpg"
    elif not review_artifacts and (root / "overview.jpg").exists():
        _safe_remove(root / "overview.jpg", root)
    _write_json(root / "manifest.json", manifest)
    return manifest
