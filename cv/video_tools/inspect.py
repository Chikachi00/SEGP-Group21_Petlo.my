"""Inspect true source-frame windows and reversible original-pixel crops."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from PIL import Image, ImageDraw

from .media import extract_frames


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _within(root: Path, relative: str) -> Path:
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Packet artifact path escapes the packet directory.")
    return result


def _remove_owned(path: Path, owner: Path) -> None:
    resolved, root = path.resolve(), owner.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Refusing to remove a directory outside this output area.")
    if resolved.exists():
        shutil.rmtree(resolved)


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


def _relocate(value: Any, before: Path, after: Path) -> Any:
    if isinstance(value, dict):
        return {key: _relocate(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate(item, before, after) for item in value]
    if isinstance(value, str):
        if value == str(before):
            return str(after)
        if value.startswith(str(before) + os.sep):
            return str(after / Path(value).relative_to(before))
    return value


def _crop_record(parent: dict, box: tuple[int, int, int, int], target: Path, kind: str, **extra: Any) -> dict:
    left, top, right, bottom = box
    with Image.open(parent["path"]) as image:
        image.crop(box).convert("RGB").save(target, quality=95, subsampling=0)
    return {
        **parent,
        **extra,
        "path": str(target.resolve()),
        "parent_path": parent["path"],
        "kind": kind,
        "width": right - left,
        "height": bottom - top,
        "crop": [left, top, right - left, bottom - top],
        "scale_x": 1.0,
        "scale_y": 1.0,
    }


def inspect_window(pack_root, video_id, start_sec, end_sec, tools, sampling="source", tiles=False, frame_id=None, bboxes=None):
    """Generate an indexed local window; images are grouped in batches of at most 8.

    `bboxes` is an optional list of {frame_id, bbox: [x1,y1,x2,y2], label?}.
    Boxes use display-oriented ORIGINAL pixels. End time is exclusive.
    """
    root = Path(pack_root).resolve()
    manifest = _read(root / "manifest.json")
    video = next((item for item in manifest["videos"] if item["id"] == video_id), None)
    if video is None or video.get("status") != "complete":
        raise ValueError("Unknown video ID or video has not been prepared successfully.")
    start, end = _finite(start_sec, "start_sec"), _finite(end_sec, "end_sec")
    if start < 0 or end <= start or end > float(video["duration"]) + 0.05:
        raise ValueError("Require 0 <= start < end <= video duration (end is exclusive).")
    if sampling not in ("source", "10"):
        raise ValueError("sampling must be 'source' or '10'.")
    if frame_id is not None and (isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0):
        raise ValueError("frame_id must be a non-negative source-frame integer.")
    if tiles and frame_id is None:
        raise ValueError("Use --frame-id with --tiles to inspect one frame without generating unnecessary tiles.")
    source = Path(video["source"])
    if root == source.parent.resolve() or root.is_relative_to(source.parent.resolve()):
        raise ValueError("Inspection output must stay outside the source video directory.")
    if not source.is_file() or _sha256(source) != video["source_sha256"]:
        raise ValueError("Source video changed or is missing; run prepare again before inspecting.")
    frames = _read(_within(root, video["paths"]["frame_index"]))
    available = [item for item in frames if start <= item["t_sec"] < end]
    if frame_id is not None:
        available = [item for item in available if item["frame_id"] == frame_id]
    if not available:
        raise ValueError("No source frames in this window, or requested frame is outside it.")
    selected = available
    if sampling == "10" and frame_id is None:
        selected = []
        previous_slot = None
        for item in available:
            slot = math.floor((item["t_sec"] - start) * 10 + 1e-7)
            if slot != previous_slot:
                selected.append(item)
                previous_slot = slot
    boxes = bboxes or []
    if not isinstance(boxes, list):
        raise ValueError("Boxes input must be a JSON list.")
    selected_ids = {item["frame_id"] for item in selected}
    width, height = int(video["width"]), int(video["height"])
    for item in boxes:
        if (not isinstance(item, dict) or isinstance(item.get("frame_id"), bool)
                or not isinstance(item.get("frame_id"), int) or item.get("frame_id") not in selected_ids):
            raise ValueError("Each box must refer to a frame selected by this inspection.")
        box = item.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("bbox must contain [x1,y1,x2,y2].")
        x1, y1, x2, y2 = [_finite(value, "bbox coordinate") for value in box]
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("bbox must lie inside display-oriented original dimensions.")
    config = {"version": 2, "source_sha256": video["source_sha256"], "toolchain": tools.version,
              "video_id": video_id, "start": start, "end": end, "sampling": sampling,
              "tiles": bool(tiles), "frame_id": frame_id, "boxes": boxes}
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]
    parent = root / "inspections" / video_id
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / digest
    report_path = destination / "inspection.json"
    if report_path.is_file():
        try:
            cached = _read(report_path)
            for item in cached["images"] + cached["crops"]:
                cached_image = _within(root, item["path"])
                with Image.open(cached_image) as image:
                    image.verify()
            if not (destination / "batches.json").is_file():
                raise ValueError("Missing batch index")
            cached["cached"] = True
            return cached
        except (OSError, ValueError, KeyError):
            pass
    temporary = Path(tempfile.mkdtemp(prefix=".inspection-", dir=parent)).resolve()
    try:
        images = extract_frames(source, selected, temporary / "frames", tools, max_side=None)
        for image in images:
            image["kind"] = "frame"
        crops = []
        crop_dir = temporary / "crops"
        crop_dir.mkdir()
        if tiles:
            image = images[0]
            for row in range(4):
                for column in range(4):
                    cell_x1, cell_x2 = column * width / 4, (column + 1) * width / 4
                    cell_y1, cell_y2 = row * height / 4, (row + 1) * height / 4
                    margin_x, margin_y = width / 40, height / 40
                    box = (max(0, math.floor(cell_x1 - margin_x)), max(0, math.floor(cell_y1 - margin_y)),
                           min(width, math.ceil(cell_x2 + margin_x)), min(height, math.ceil(cell_y2 + margin_y)))
                    crops.append(_crop_record(image, box, crop_dir / f"tile_{row}_{column}.jpg", "tile", row=row, column=column))
        by_frame = {image["frame_id"]: image for image in images}
        for number, item in enumerate(boxes):
            x1, y1, x2, y2 = item["bbox"]
            margin_x, margin_y = (x2 - x1) * 0.25, (y2 - y1) * 0.25
            box = (max(0, math.floor(x1 - margin_x)), max(0, math.floor(y1 - margin_y)),
                   min(width, math.ceil(x2 + margin_x)), min(height, math.ceil(y2 + margin_y)))
            crops.append(_crop_record(by_frame[item["frame_id"]], box, crop_dir / f"bbox_{number:04d}.jpg", "bbox", label=item.get("label")))
        batches = []
        # Keep window frames and crops in separate reading batches so coordinates remain clear.
        for kind, items in (("frames", images), ("crops", crops)):
            for offset in range(0, len(items), 8):
                batches.append({"kind": kind, "batch_id": len(batches), "images": items[offset:offset + 8]})
        report = {"schema_version": 1, "video_id": video_id, "start_sec": start, "end_sec": end,
                  "sampling": sampling, "images": images, "crops": crops, "batches": batches,
                  "output_dir": str(temporary), "report_path": str(temporary / "inspection.json"), "cached": False,
                  "coordinate_system": "display-oriented original pixels; original_x=crop_x+image_x/scale_x",
                  "reading_limit": 8, "source_sha256": video["source_sha256"]}
        report = _relocate(report, temporary, destination)
        _write(temporary / "inspection.json", report)
        _write(temporary / "batches.json", report["batches"])
        _remove_owned(destination, parent)
        temporary.rename(destination)
        return report
    except Exception:
        _remove_owned(temporary, parent)
        raise
