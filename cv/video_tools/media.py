"""Decode local videos with FFmpeg and preserve their actual frame timestamps.

No files are read, processes launched, or files created on import.  All media
operations are explicit calls; video inputs are always opened read-only.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Any, Iterable


# Bound software decoding to avoid pathological auto-thread behavior on some
# 4K HEVC files. This does not resample frames or alter their timestamps.
DECODE_THREADS = 4
FILTER_THREADS = 1


class MediaError(RuntimeError):
    """An input cannot be decoded or its image/timestamp correspondence failed."""


class ToolchainError(MediaError):
    """A matching, usable ffmpeg/ffprobe pair was not found."""


def _run(arguments: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"Cannot run {Path(arguments[0]).name}: {exc}") from exc
    if result.returncode:
        details = result.stderr.decode("utf-8", "replace")[-12000:]
        raise MediaError(f"{Path(arguments[0]).name} exited {result.returncode}: {details.strip()}")
    return result


@dataclass(frozen=True)
class Toolchain:
    ffmpeg: str
    ffprobe: str
    version: dict[str, str]

    @classmethod
    def discover(cls, ffmpeg_dir: str | Path | None = None) -> "Toolchain":
        """Find a co-located pair; an explicit directory is searched recursively.

        Multiple pairs in the same search root are an error.  There is no
        installation or download fallback and PATH is never modified.
        """
        executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        probe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        root = ffmpeg_dir or os.environ.get("VIDEO_TOOLS_FFMPEG_DIR") or os.environ.get("FFMPEG_DIR")
        if root is None:
            local_root = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg"
            if local_root.is_dir():
                root = local_root
        if root is not None:
            directory = Path(root).expanduser().resolve()
            if not directory.is_dir():
                raise ToolchainError(f"FFmpeg directory does not exist: {directory}")
            pairs = sorted({p.resolve() for p in directory.rglob(executable)
                            if p.is_file() and (p.parent / probe_name).is_file()}, key=str)
            if len(pairs) != 1:
                message = "No matching ffmpeg/ffprobe pair" if not pairs else "Multiple FFmpeg pairs"
                raise ToolchainError(f"{message} in {directory}; specify one bin directory.")
            binary = pairs[0]
            probe = binary.parent / probe_name
        else:
            found = shutil.which(executable)
            if not found:
                raise ToolchainError("FFmpeg is unavailable; supply --ffmpeg-dir with a portable bin directory.")
            binary = Path(found).resolve()
            probe = binary.parent / probe_name
            if not probe.is_file():
                raise ToolchainError(f"Matching ffprobe is missing beside {binary}")
        versions = {}
        for name, path in (("ffmpeg", binary), ("ffprobe", probe)):
            result = _run([str(path), "-version"], timeout=20)
            versions[name] = result.stdout.decode("utf-8", "replace").splitlines()[0]
        return cls(str(binary), str(probe), versions)


def _source_path(source: str | Path) -> Path:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise MediaError(f"Video file does not exist: {path}")
    return path


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        if isinstance(value, str) and "/" in value:
            numerator, denominator = value.split("/", 1)
            result = float(numerator) / float(denominator)
        else:
            result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def probe_video(source: str | Path, tools: Toolchain) -> dict[str, Any]:
    """Read container/stream metadata; probing alone does not prove decodability."""
    path = _source_path(source)
    result = _run([tools.ffprobe, "-v", "error", "-select_streams", "v:0",
                   "-show_streams", "-show_format", "-of", "json", str(path)])
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise MediaError(f"No readable video stream in {path.name}") from exc
    encoded_width, encoded_height = int(stream["width"]), int(stream["height"])
    if encoded_width <= 0 or encoded_height <= 0:
        raise MediaError(f"Invalid encoded dimensions in {path.name}")
    rotation = _number(stream.get("tags", {}).get("rotate"), 0.0)
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            rotation = _number(side_data["rotation"], rotation)
            break
    rotation = float(rotation or 0.0)
    quarter_turn = round(rotation / 90) % 4
    width, height = ((encoded_height, encoded_width) if quarter_turn % 2
                     else (encoded_width, encoded_height))
    warnings = []
    if abs(rotation / 90 - round(rotation / 90)) > 0.001:
        warnings.append("Non-orthogonal rotation: decoded display dimensions will be verified.")
    return {
        "source": str(path), "codec_name": stream.get("codec_name"),
        "profile": stream.get("profile"), "pix_fmt": stream.get("pix_fmt"),
        "encoded_width": encoded_width, "encoded_height": encoded_height,
        "width": width, "height": height, "rotation": rotation,
        "sample_aspect_ratio": stream.get("sample_aspect_ratio", "1:1"),
        "duration": _number(stream.get("duration"), _number(payload.get("format", {}).get("duration"))),
        "start_time": _number(stream.get("start_time"), 0.0),
        "time_base": _number(stream.get("time_base"), 0.0),
        "r_frame_rate": _number(stream.get("r_frame_rate"), 0.0),
        "avg_frame_rate": _number(stream.get("avg_frame_rate"), 0.0),
        "frames_count": int(stream.get("nb_frames", 0)) if str(stream.get("nb_frames", "")).isdigit() else None,
        "warnings": warnings,
    }


def _read_frame_index(source: Path, tools: Toolchain) -> list[dict[str, Any]]:
    result = _run([tools.ffprobe, "-v", "error", "-threads", str(DECODE_THREADS), "-select_streams", "v:0", "-show_frames",
                   "-show_entries", "frame=pts,pts_time,best_effort_timestamp,best_effort_timestamp_time",
                   "-of", "json", str(source)])
    try:
        decoded = json.loads(result.stdout).get("frames", [])
    except ValueError as exc:
        raise MediaError(f"Invalid frame index for {source.name}") from exc
    frames = []
    first_pts = None
    for frame_id, raw in enumerate(decoded):
        timestamp_source = "pts_time"
        pts_sec = _number(raw.get(timestamp_source))
        if pts_sec is None:
            timestamp_source = "best_effort_timestamp_time"
            pts_sec = _number(raw.get(timestamp_source))
        if pts_sec is None:
            raise MediaError(f"Frame {frame_id} has no usable timestamp in {source.name}")
        if first_pts is None:
            first_pts = pts_sec
        if frames and pts_sec <= frames[-1]["pts_sec"]:
            raise MediaError(f"Non-increasing frame timestamps at frame {frame_id} in {source.name}")
        frames.append({"frame_id": frame_id, "pts_sec": pts_sec,
                       "t_sec": round(pts_sec - first_pts, 9), "timestamp_source": timestamp_source})
    if not frames:
        raise MediaError(f"No decoded video frames in {source.name}")
    return frames


def _parse_showinfo(line: str) -> dict[str, Any] | None:
    if "showinfo" not in line or "pts_time:" not in line:
        return None
    patterns = {"n": r"\bn:\s*(\d+)", "pts": r"\bpts:\s*(-?\d+)",
                "pts_sec": r"\bpts_time:\s*([-+\d.eE]+)", "size": r"\bs:(\d+)x(\d+)"}
    matches = {key: re.search(pattern, line) for key, pattern in patterns.items()}
    if not all(matches.values()):
        return None
    return {"n": int(matches["n"].group(1)), "pts": int(matches["pts"].group(1)),
            "pts_sec": float(matches["pts_sec"].group(1)),
            "width": int(matches["size"].group(1)), "height": int(matches["size"].group(2))}


def _stderr_reader(pipe, log_lines: list[str], showinfos: list[dict[str, Any]]) -> None:
    for raw in iter(pipe.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        log_lines.append(line)
        record = _parse_showinfo(line)
        if record is not None:
            showinfos.append(record)
    pipe.close()


def _timestamp_matches(actual: float, expected: float, time_base: float = 0.0) -> bool:
    # FFmpeg showinfo prints six significant digits; ffprobe uses six decimals.
    precision = max(abs(actual), abs(expected), 1.0) * 0.000002
    return abs(actual - expected) <= max(0.00001, precision, abs(time_base) * 2)


def _validate_timestamps(showinfos: list[dict[str, Any]], frames: list[dict[str, Any]],
                         *, time_base: float = 0.0) -> None:
    if len(showinfos) != len(frames):
        raise MediaError(f"Decoded timestamp count mismatch: {len(showinfos)} vs {len(frames)} expected frames")
    for index, (actual, expected) in enumerate(zip(showinfos, frames)):
        if actual["n"] != index or not _timestamp_matches(actual["pts_sec"], expected["pts_sec"], time_base):
            raise MediaError(f"Actual decoded PTS does not match frame {expected['frame_id']}: "
                             f"{actual['pts_sec']} vs {expected['pts_sec']}")


def _read_exact(pipe, count: int) -> bytes:
    parts = []
    remaining = count
    while remaining:
        chunk = pipe.read(remaining)
        if not chunk:
            break
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def scan_video(source: str | Path, tools: Toolchain) -> tuple[dict, list[dict], list[dict]]:
    """Fully decode in software and measure consecutive low-resolution gray frames.

    Actual frame timestamps are cross-checked against a complete ffprobe index.
    Motion is an unclassified review heuristic, not an action/event prediction.
    Static and genuinely repeated source frames are valid.
    """
    path = _source_path(source)
    metadata = probe_video(path, tools)
    frames = _read_frame_index(path, tools)
    arguments = [tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-xerror",
                 "-copyts", "-filter_threads", str(FILTER_THREADS), "-hwaccel", "none",
                 "-threads", str(DECODE_THREADS), "-i", str(path), "-map", "0:v:0",
                 "-an", "-sn", "-dn", "-vf", "showinfo,scale=160:90:flags=area,format=gray",
                 "-fps_mode", "passthrough", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"]
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise MediaError(f"Cannot start decoder: {exc}") from exc
    log_lines, showinfos, motion_records = [], [], []
    reader = threading.Thread(target=_stderr_reader, args=(process.stderr, log_lines, showinfos), daemon=True)
    reader.start()
    try:
        try:
            import numpy as np
        except ImportError:
            np = None
        previous = None
        count = 160 * 90
        while True:
            raw = _read_exact(process.stdout, count)
            if not raw:
                break
            if len(raw) != count:
                raise MediaError("Decoder ended with an incomplete raw frame")
            frame_id = len(motion_records)
            if frame_id >= len(frames):
                raise MediaError("Decoder emitted more frames than the source index")
            current = np.frombuffer(raw, dtype=np.uint8).astype(np.int16) if np is not None else raw
            score = 0.0 if previous is None else (
                float(np.abs(current - previous).mean() / 255.0) if np is not None
                else sum(abs(a - b) for a, b in zip(current, previous)) / count / 255.0)
            frame = frames[frame_id]
            motion_records.append({"frame_id": frame_id, "pts_sec": frame["pts_sec"],
                                   "t_sec": frame["t_sec"], "motion_score": round(score, 9)})
            previous = current
        process.stdout.close()
        code = process.wait(timeout=600)
        reader.join(timeout=20)
        if reader.is_alive():
            raise MediaError("Decoder log reader did not finish")
        if code:
            raise MediaError(f"Software decoder exited {code}: " + "\n".join(log_lines[-30:]))
        if len(motion_records) != len(frames):
            raise MediaError(f"Full decode returned {len(motion_records)} of {len(frames)} source frames")
        _validate_timestamps(showinfos, frames, time_base=metadata.get("time_base", 0.0))
        metadata["width"], metadata["height"] = showinfos[0]["width"], showinfos[0]["height"]
        if any((info["width"], info["height"]) != (metadata["width"], metadata["height"]) for info in showinfos):
            raise MediaError("Source display dimensions change during this video; split it before preparing")
        metadata["frames_count"] = len(frames)
        if metadata["duration"] is None:
            last_delta = frames[-1]["t_sec"] - frames[-2]["t_sec"] if len(frames) > 1 else 0.0
            metadata["duration"] = frames[-1]["t_sec"] + last_delta
        if any(frame["timestamp_source"] != "pts_time" for frame in frames):
            metadata["warnings"].append("Some frame timestamps use decoder-estimated best_effort_timestamp_time.")
        if len(frames) > 2:
            intervals = [frames[i]["pts_sec"] - frames[i-1]["pts_sec"] for i in range(1, len(frames))]
            tolerance = max(0.00001, metadata.get("time_base", 0.0) * 2)
            metadata["variable_frame_intervals"] = max(intervals) - min(intervals) > tolerance
        else:
            metadata["variable_frame_intervals"] = False
        return metadata, frames, motion_records
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout and not process.stdout.closed:
            process.stdout.close()
        reader.join(timeout=20)


def _selection_expression(ids: list[int]) -> str:
    """Collapse contiguous runs and balance sparse unions for FFmpeg's parser.

    A long left-associated sum of eq() expressions exceeds libavutil's
    expression recursion limit even for a two-second 60-fps review window.
    """
    runs = []
    first = last = ids[0]
    for value in ids[1:]:
        if value == last + 1:
            last = value
        else:
            runs.append((first, last))
            first = last = value
    runs.append((first, last))
    terms = [f"eq(n\\,{a})" if a == b else f"between(n\\,{a}\\,{b})" for a, b in runs]
    def balanced(values):
        if len(values) == 1:
            return values[0]
        middle = len(values) // 2
        return f"({balanced(values[:middle])}+{balanced(values[middle:])})"
    return balanced(terms)


def extract_frames(source: str | Path, selected_frames: Iterable[dict[str, Any]],
                   output_dir: str | Path, tools: Toolchain,
                   max_side: int | None = 1280) -> list[dict[str, Any]]:
    """Select source frame IDs without adding frames; verify actual emitted PTS.

    Returned paths are absolute. max_side=None keeps decoded display dimensions.
    crop/scale metadata maps returned images back to the rotated display frame.
    """
    path = _source_path(source)
    directory = Path(output_dir).expanduser().resolve()
    if directory == path.parent or path.parent in directory.parents:
        raise MediaError("Extraction output must be outside the source video's directory")
    frames = sorted(list(selected_frames), key=lambda frame: frame["frame_id"])
    ids = [frame.get("frame_id") for frame in frames]
    if any(isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0 for frame_id in ids):
        raise MediaError("Selected frame IDs must be non-negative integers")
    if len(set(ids)) != len(ids):
        raise MediaError("Selected frame IDs must be unique")
    if any(_number(frame.get("pts_sec")) is None or _number(frame.get("t_sec")) is None for frame in frames):
        raise MediaError("Selected frames require finite pts_sec and t_sec values")
    if max_side is not None and (isinstance(max_side, bool) or not isinstance(max_side, int) or max_side < 2):
        raise MediaError("max_side must be None or an integer of at least 2 pixels")
    if not frames:
        return []
    from PIL import Image
    directory.mkdir(parents=True, exist_ok=True)
    expression = _selection_expression(ids)
    filters = f"select='{expression}',showinfo"
    if max_side is not None:
        filters += (f",scale=w='min(iw,{max_side})':h='min(ih,{max_side})'"
                    ":force_original_aspect_ratio=decrease:flags=lanczos")
    pattern = directory / "_extract_%06d.jpg"
    result = _run([tools.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "info", "-xerror",
                   "-copyts", "-filter_threads", str(FILTER_THREADS), "-hwaccel", "none",
                   "-threads", str(DECODE_THREADS), "-i", str(path), "-map", "0:v:0",
                   "-an", "-sn", "-dn", "-vf", filters, "-fps_mode", "passthrough",
                   "-q:v", "2", "-f", "image2", str(pattern)])
    showinfos = [info for line in result.stderr.decode("utf-8", "replace").splitlines()
                 if (info := _parse_showinfo(line)) is not None]
    _validate_timestamps(showinfos, frames)
    generated = sorted(directory.glob("_extract_*.jpg"))
    if len(generated) != len(frames):
        raise MediaError(f"Extraction wrote {len(generated)} images for {len(frames)} selected frames")
    records = []
    for temporary, frame, actual in zip(generated, frames, showinfos):
        with Image.open(temporary) as picture:
            picture.verify()
        with Image.open(temporary) as picture:
            width, height = picture.size
        source_width, source_height = actual["width"], actual["height"]
        if max_side is None and (width, height) != (source_width, source_height):
            raise MediaError("Unscaled extraction dimensions differ from the decoded source frame")
        if max_side is not None and max(width, height) > max_side:
            raise MediaError("Extracted image exceeds max_side")
        destination = directory / f"frame_{frame['frame_id']:06d}.jpg"
        os.replace(temporary, destination)
        records.append({"frame_id": frame["frame_id"], "pts_sec": frame["pts_sec"],
                        "t_sec": frame["t_sec"], "path": str(destination),
                        "width": width, "height": height,
                        "source_width": source_width, "source_height": source_height,
                        "scale_x": width / source_width, "scale_y": height / source_height,
                        "crop": [0, 0, source_width, source_height]})
    return records


def iter_source_frames(source, frames, metadata, tools):
    """Yield mutable original-size BGR frames, validating decoded IDs and PTS.

    Consume the generator completely before accepting a run. Selected frame
    records come from the complete source index, never an average-FPS clock.
    """
    import numpy as np
    path = _source_path(source)
    records = list(frames)
    if not records:
        return
    ids = [r["frame_id"] for r in records]
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in ids) or ids != sorted(set(ids)):
        raise MediaError("Frame IDs must be unique, sorted non-negative integers")
    width, height = metadata["width"], metadata["height"]
    if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0:
        raise MediaError("Positive original display dimensions are required")
    if ids == list(range(ids[0], ids[-1] + 1)):
        selection = f"between(n\\,{ids[0]}\\,{ids[-1]})"
    else:
        selection = "+".join(f"eq(n\\,{i})" for i in ids)
    arguments = [tools.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-xerror", "-copyts",
                 "-filter_threads", str(FILTER_THREADS), "-hwaccel", "none", "-threads", str(DECODE_THREADS),
                 "-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn",
                 "-vf", f"select='{selection}',showinfo", "-frames:v", str(len(records)),
                 "-fps_mode", "passthrough", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    logs, actual = [], []
    reader = threading.Thread(target=_stderr_reader, args=(process.stderr, logs, actual), daemon=True)
    reader.start()
    try:
        for record in records:
            raw = _read_exact(process.stdout, width * height * 3)
            if len(raw) != width * height * 3:
                raise MediaError(f"Decoder stopped before complete frame {record['frame_id']}")
            yield record, np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()
        if process.stdout.read(1):
            raise MediaError("Decoder emitted more frames than requested")
        process.stdout.close()
        code = process.wait(timeout=600)
        reader.join(timeout=20)
        if reader.is_alive() or code:
            raise MediaError("BGR decoder failed: " + "\n".join(logs[-20:]))
        _validate_timestamps(actual, records, time_base=metadata.get("time_base", 0.0))
        if any((info["width"], info["height"]) != (width, height) for info in actual):
            raise MediaError("BGR dimensions differ from the original display frame")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout and not process.stdout.closed:
            process.stdout.close()
        reader.join(timeout=20)
