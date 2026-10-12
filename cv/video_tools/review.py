"""Validate tracking output and build a small, source-backed review package.

The figures and counts describe submitted predictions.  They are deliberately
not accuracy measurements: no ground-truth labels are supplied to this module.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .media import Toolchain

_FIELDS = {"video_id", "frame_id", "t_sec", "label", "track_id", "bbox", "confidence", "status"}
_LOW_CONFIDENCE = 0.4
_JUMP_FRACTION = 0.2
_WINDOW_RADIUS = 1.0
_MAX_WINDOWS = 2
_MAX_STILLS = 8
_VERSION = 2


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON 中不允许非有限数 {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _pack_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("资料包路径必须为非空相对路径")
    candidate = (root / relative).resolve()
    if Path(relative).is_absolute() or not candidate.is_relative_to(root):
        raise ValueError(f"资料包路径超出资料包目录：{relative}")
    return candidate


def _video_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("videos"), list):
        raise ValueError("manifest.json 缺少 videos 列表")
    videos: dict[str, dict[str, Any]] = {}
    for video in manifest["videos"]:
        if not isinstance(video, dict) or not isinstance(video.get("id"), str) or not video["id"]:
            raise ValueError("manifest 中每个视频必须有非空字符串 id")
        if video["id"] in videos:
            raise ValueError(f"manifest 中视频 id 重复：{video['id']}")
        if video.get("status") not in ("complete", "failed"):
            raise ValueError(f"manifest 中 {video['id']} 的 status 必须为 complete 或 failed")
        if video["status"] == "complete":
            if not all(_integer(video.get(key)) and video[key] > 0 for key in ("width", "height", "frames_count")):
                raise ValueError(f"manifest 中 {video['id']} 的显示尺寸与 frames_count 必须为正整数")
        videos[video["id"]] = video
    return videos


def _frame_maps(videos: dict[str, dict[str, Any]], indexes: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, dict[int, int]], dict[str, dict[int, float]]]:
    by_id: dict[str, dict[int, dict[str, Any]]] = {}
    positions: dict[str, dict[int, int]] = {}
    tolerances: dict[str, dict[int, float]] = {}
    for video_id, records in indexes.items():
        if video_id not in videos:
            raise ValueError(f"frame_index 引用了未知视频：{video_id}")
        if not isinstance(records, list) or not records:
            raise ValueError(f"{video_id} 的 frame_index 必须为非空列表")
        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        for record in records:
            if not isinstance(record, dict) or not _integer(record.get("frame_id")) or record["frame_id"] < 0:
                raise ValueError(f"{video_id} 的 frame_id 必须为非负整数")
            if record["frame_id"] in seen:
                raise ValueError(f"{video_id} 的源 frame_id 重复：{record['frame_id']}")
            if not _finite(record.get("t_sec")) or record["t_sec"] < 0:
                raise ValueError(f"{video_id} 的源 t_sec 无效")
            if not _finite(record.get("pts_sec")):
                raise ValueError(f"{video_id} 的源 pts_sec 无效")
            if not isinstance(record.get("timestamp_source"), str) or not record["timestamp_source"]:
                raise ValueError(f"{video_id} 的源 timestamp_source 无效")
            seen.add(record["frame_id"])
            normalized.append(record)
        normalized.sort(key=lambda item: item["frame_id"])
        if [item["frame_id"] for item in normalized] != list(range(len(normalized))):
            raise ValueError(f"{video_id} 的 frame_index 必须覆盖从 0 开始的全部解码帧")
        if any(b["t_sec"] <= a["t_sec"] for a, b in zip(normalized, normalized[1:])):
            raise ValueError(f"{video_id} 的源时间戳必须随 frame_id 严格递增")
        declared_count = videos[video_id].get("frames_count")
        if _integer(declared_count) and declared_count != len(normalized):
            raise ValueError(f"{video_id} 的 frames_count 与 frame_index 数量不一致")
        by_id[video_id] = {item["frame_id"]: item for item in normalized}
        positions[video_id] = {item["frame_id"]: position for position, item in enumerate(normalized)}
        tolerances[video_id] = {}
        for position, item in enumerate(normalized):
            intervals = []
            if position:
                intervals.append(item["t_sec"] - normalized[position - 1]["t_sec"])
            if position + 1 < len(normalized):
                intervals.append(normalized[position + 1]["t_sec"] - item["t_sec"])
            # A single-frame file cannot justify an assumed frame duration.
            tolerances[video_id][item["frame_id"]] = (min(intervals) / 2 if intervals else 0) + 0.001
    return by_id, positions, tolerances


def validate_results(rows: list[dict[str, Any]], manifest: dict[str, Any], frame_indexes: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Return canonical tracking rows, or raise ValueError before any output is written.

    Source coordinates use the display-oriented original dimensions.  Submitted
    times must match the source frame within half its local interval plus 1 ms.
    """
    videos = _video_map(manifest)
    frames, _, tolerances = _frame_maps(videos, frame_indexes)
    if not isinstance(rows, list) or not rows:
        raise ValueError("tracking JSONL 至少需要一条记录")
    normalized = []
    seen: set[tuple[Any, ...]] = set()
    for number, row in enumerate(rows, 1):
        prefix = f"tracking 第 {number} 条："
        if not isinstance(row, dict) or set(row) != _FIELDS:
            actual = set(row) if isinstance(row, dict) else set()
            raise ValueError(prefix + f"字段不符；缺少 {sorted(_FIELDS - actual)}，多余 {sorted(actual - _FIELDS)}")
        video_id = row["video_id"]
        if not isinstance(video_id, str) or video_id not in videos:
            raise ValueError(prefix + "video_id 未在 manifest 中声明")
        video = videos[video_id]
        if video.get("status") != "complete" or video_id not in frames:
            raise ValueError(prefix + f"视频 {video_id} 未成功建立完整源帧索引")
        if not _integer(row["frame_id"]) or row["frame_id"] < 0 or row["frame_id"] not in frames[video_id]:
            raise ValueError(prefix + "frame_id 必须为源索引内的非负整数")
        frame = frames[video_id][row["frame_id"]]
        if not _finite(row["t_sec"]) or abs(row["t_sec"] - frame["t_sec"]) > tolerances[video_id][row["frame_id"]] + 1e-12:
            raise ValueError(prefix + f"t_sec 与源帧时间不匹配（源 {frame['t_sec']:.6f} 秒，容差 {tolerances[video_id][row['frame_id']]:.6f} 秒）")
        if row["label"] not in ("dog", "disc"):
            raise ValueError(prefix + "label 必须为 dog 或 disc")
        track_id = row["track_id"]
        if not ((_integer(track_id)) or (isinstance(track_id, str) and track_id.strip())):
            raise ValueError(prefix + "track_id 必须为整数或非空字符串，不能为 bool")
        if row["status"] not in ("detected", "missing"):
            raise ValueError(prefix + "status 必须为 detected 或 missing")
        confidence = row["confidence"]
        if confidence is not None and (not _finite(confidence) or not 0 <= confidence <= 1):
            raise ValueError(prefix + "confidence 必须为 null 或 0..1 的有限数")
        box = row["bbox"]
        if row["status"] == "missing":
            if box is not None:
                raise ValueError(prefix + "missing 记录的 bbox 必须为 null")
        else:
            width, height = video.get("width"), video.get("height")
            if not (_integer(width) and _integer(height) and width > 0 and height > 0):
                raise ValueError(prefix + "manifest 缺少有效的显示方向原尺寸")
            if not isinstance(box, list) or len(box) != 4 or not all(_finite(value) for value in box):
                raise ValueError(prefix + "detected 的 bbox 必须为四个有限数")
            x1, y1, x2, y2 = box
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError(prefix + f"bbox 需为正面积且位于显示原尺寸 {width}×{height} 内")
        key = (video_id, row["frame_id"], row["label"], type(track_id).__name__, track_id)
        if key in seen:
            raise ValueError(prefix + "同一视频/帧/类别/轨迹有重复记录")
        seen.add(key)
        normalized.append({**row, "t_sec": float(frame["t_sec"]), "bbox": [float(value) for value in box] if box is not None else None,
                           "confidence": float(confidence) if confidence is not None else None})
    return sorted(normalized, key=lambda item: (item["video_id"], item["frame_id"], item["label"], type(item["track_id"]).__name__, str(item["track_id"])))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
            except (ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"tracking JSONL 第 {line_number} 行无效：{error}") from error
            rows.append(row)
    return rows


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_signature(videos: dict[str, dict[str, Any]], indexes: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, str | None]]:
    signature = []
    hashes: dict[str, str | None] = {}
    for video_id in sorted(videos):
        video = videos[video_id]
        source = video.get("source")
        source_path = Path(source) if isinstance(source, str) else None
        declared_hash = video.get("source_sha256", video.get("sha256"))
        if video.get("status") == "complete":
            if source_path is None or not source_path.is_file():
                raise ValueError(f"完整索引的视频原片不可读取：{video_id}")
            actual_hash = _file_sha256(source_path)
            if declared_hash is not None and actual_hash != declared_hash:
                raise ValueError(f"{video_id} 原片内容已变化，需重新 prepare 后再复盘")
        else:
            actual_hash = declared_hash
        hashes[video_id] = actual_hash
        signature.append({"id": video_id, "source_sha256": actual_hash,
                          "width": video.get("width"), "height": video.get("height"), "frames_count": video.get("frames_count"),
                          "role": video.get("role"), "status": video.get("status"), "frame_index": indexes.get(video_id)})
    return _digest(signature), hashes


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = Counter((row["video_id"], row["frame_id"], row["label"]) for row in rows)
    entries = [[*key, amount] for key, amount in sorted(count.items())]
    return {"signature": _digest(entries), "record_count": len(rows), "frame_label_count": len(entries), "entries": entries}


def _metrics_and_candidates(rows: list[dict[str, Any]], videos: dict[str, dict[str, Any]], positions: dict[str, dict[int, int]], processing_seconds: float | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    per_video = {video_id: {"record_count": 0, "missing_record_count": 0, "low_confidence_record_count": 0,
                           "trajectory_gap_count": 0, "jump_candidate_count": 0} for video_id in videos}
    candidates = []
    for row in rows:
        metrics = per_video[row["video_id"]]
        metrics["record_count"] += 1
        base = {"video_id": row["video_id"], "frame_id": row["frame_id"], "t_sec": row["t_sec"], "label": row["label"], "track_id": row["track_id"]}
        if row["status"] == "missing":
            metrics["missing_record_count"] += 1
            candidates.append({**base, "kind": "missing", "priority": 0})
        elif row["confidence"] is not None and row["confidence"] < _LOW_CONFIDENCE:
            metrics["low_confidence_record_count"] += 1
            candidates.append({**base, "kind": "low_confidence", "confidence": row["confidence"], "priority": 1})
        grouped[(row["video_id"], row["label"], type(row["track_id"]).__name__, row["track_id"])].append(row)
    for track_rows in grouped.values():
        track_rows.sort(key=lambda item: item["frame_id"])
        for before, after in zip(track_rows, track_rows[1:]):
            video_id = after["video_id"]
            skipped = positions[video_id][after["frame_id"]] - positions[video_id][before["frame_id"]] - 1
            base = {"video_id": video_id, "frame_id": after["frame_id"], "t_sec": after["t_sec"], "label": after["label"], "track_id": after["track_id"]}
            if skipped > 0:
                per_video[video_id]["trajectory_gap_count"] += 1
                candidates.append({**base, "kind": "trajectory_gap", "source_frames_without_track_records": skipped,
                                   "previous_frame_id": before["frame_id"], "priority": 3})
            dt = after["t_sec"] - before["t_sec"]
            if before["bbox"] is not None and after["bbox"] is not None and 0 < dt <= 0.25 + 1e-12:
                b, a = before["bbox"], after["bbox"]
                displacement = math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)
                diagonal = math.hypot(videos[video_id]["width"], videos[video_id]["height"])
                if displacement > diagonal * _JUMP_FRACTION:
                    per_video[video_id]["jump_candidate_count"] += 1
                    candidates.append({**base, "kind": "jump", "previous_frame_id": before["frame_id"], "dt_sec": dt,
                                       "center_displacement_px": displacement, "display_diagonal_fraction": displacement / diagonal, "priority": 2})
    totals = {key: sum(item[key] for item in per_video.values()) for key in ("record_count", "missing_record_count", "low_confidence_record_count", "trajectory_gap_count", "jump_candidate_count")}
    metrics = {**totals, "processing_seconds": processing_seconds, "per_video": per_video,
               "definitions": {"missing_record_count": "输入显式提交 status=missing 的记录数；不代表真实漏检数。",
                               "low_confidence_record_count": "detected 且 confidence<0.4；null 不计入低置信度。",
                               "trajectory_gap_count": "同类别同轨迹相邻输出之间有源帧未提交该轨迹记录的区间数；可能只是稀疏采样。",
                               "jump_candidate_count": "相邻有框记录真实时间间隔<=0.25秒且中心位移>显示原图对角线20%的候选数。",
                               "processing_seconds": "调用者提供的本地算法处理时长，未提供时为 null；不是本次 review 用时。"},
               "warning": "无人工真值；这些是提交结果的诊断统计，不是 accuracy、precision、recall 或接盘判定。"}
    return metrics, candidates


def _comparison(previous_path: Path | None, source_signature: str, coverage: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    if previous_path is None:
        return {"status": "not_requested", "reason": "未指定上一版 review 报告。"}
    if previous_path.is_dir():
        previous_path = previous_path / "report.json"
    try:
        previous = _read_json(previous_path)
    except (OSError, ValueError) as error:
        return {"status": "incompatible", "reason": f"上一版报告无法读取：{error}", "previous_path": str(previous_path)}
    if not isinstance(previous, dict) or previous.get("source_signature") != source_signature:
        return {"status": "incompatible", "reason": "上一版来源签名不一致或缺失，未比较。", "previous_path": str(previous_path)}
    old_coverage = previous.get("coverage", {})
    if not isinstance(old_coverage, dict) or old_coverage.get("signature") != coverage["signature"] or old_coverage.get("record_count") != coverage["record_count"]:
        return {"status": "incompatible", "reason": "上一版覆盖的 video/frame/label 及其记录量不一致，未比较。", "previous_path": str(previous_path)}
    old_metrics = previous.get("metrics")
    if not isinstance(old_metrics, dict):
        return {"status": "incompatible", "reason": "上一版缺少诊断指标，未比较。", "previous_path": str(previous_path)}
    keys = ("missing_record_count", "low_confidence_record_count", "trajectory_gap_count", "jump_candidate_count", "processing_seconds")
    deltas = {}
    for key in keys:
        current, old = metrics.get(key), old_metrics.get(key)
        if _finite(current) and _finite(old):
            deltas[key] = {"previous": old, "current": current, "delta": current - old}
    return {"status": "compatible", "reason": "源签名和输出覆盖一致，允许比较提交结果的诊断计数。", "previous_path": str(previous_path), "deltas": deltas,
            "warning": "轨迹 ID 允许重新编号；不直接对应跨版本轨迹。计数减少不等于准确率提高，需查看画面并以人工真值确认。"}


def _select_windows(root: Path, videos: dict[str, dict[str, Any]], indexes: dict[str, list[dict[str, Any]]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = []
    for video_id in sorted(videos):
        video = videos[video_id]
        if video.get("role") != "action" or video.get("status") != "complete" or video_id not in indexes:
            continue
        records = indexes[video_id]
        first, last = min(item["t_sec"] for item in records), max(item["t_sec"] for item in records)
        choices = sorted((item for item in candidates if item["video_id"] == video_id), key=lambda item: (item["priority"], item["t_sec"], item["frame_id"]))
        path = video.get("paths", {}).get("candidates")
        if path:
            try:
                existing = _read_json(_pack_path(root, path))
                if isinstance(existing, dict):
                    existing = existing.get("windows", existing.get("candidates", []))
                if isinstance(existing, list):
                    for candidate in existing:
                        if not isinstance(candidate, dict):
                            continue
                        center = candidate.get("center_sec", candidate.get("t_sec"))
                        if center is None and _finite(candidate.get("start_sec")) and _finite(candidate.get("end_sec")):
                            center = (candidate["start_sec"] + candidate["end_sec"]) / 2
                        if _finite(center) and first <= center <= last:
                            choices.append({"video_id": video_id, "t_sec": float(center), "kind": "motion_candidate", "priority": 4,
                                            "source_candidate_id": candidate.get("id"), "score": candidate.get("score")})
            except (OSError, ValueError):
                # Tracking failures remain reviewable even if optional candidates are unavailable.
                pass
        choices.sort(key=lambda item: (item["priority"], -(item.get("score") if _finite(item.get("score")) else 0), item["t_sec"]))
        chosen: list[dict[str, Any]] = []
        for candidate in choices:
            start, end = max(first, candidate["t_sec"] - _WINDOW_RADIUS), min(last, candidate["t_sec"] + _WINDOW_RADIUS)
            if any(start <= previous["end_sec"] and end >= previous["start_sec"] for previous in chosen):
                continue
            selected = [item for item in records if start <= item["t_sec"] <= end]
            if not selected:
                continue
            chosen.append({"id": f"{video_id}-review-{len(chosen) + 1}", "video_id": video_id, "start_sec": start, "end_sec": end,
                           "center_sec": candidate["t_sec"], "reason": candidate["kind"], "candidate": candidate,
                           "frame_records": sorted(selected, key=lambda item: item["frame_id"])})
            if len(chosen) == _MAX_WINDOWS:
                break
        windows.extend(chosen)
    return windows


def _font(size: int) -> ImageFont.ImageFont:
    for path in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_still(image_record: dict[str, Any], source_video: dict[str, Any], rows: list[dict[str, Any]], outpath: Path) -> None:
    with Image.open(image_record["path"]) as original:
        picture = original.convert("RGB")
    top = 36
    canvas = Image.new("RGB", (picture.width, picture.height + top), "#111827")
    canvas.paste(picture, (0, top))
    draw = ImageDraw.Draw(canvas)
    font = _font(18)
    draw.text((10, 8), f"{source_video['id']} | frame {image_record['frame_id']} | {image_record['t_sec']:.3f}s", font=font, fill="white")
    sx, sy = picture.width / source_video["width"], picture.height / source_video["height"]
    note_y = top + 8
    for row in rows:
        color = "#22c55e" if row["label"] == "dog" else "#f97316"
        label = f"{row['label']} #{row['track_id']}"
        if row["confidence"] is not None:
            label += f" {row['confidence']:.2f}"
        if row["bbox"] is None:
            draw.text((8, note_y), f"MISSING: {label}", font=font, fill=color, stroke_width=1, stroke_fill="black")
            note_y += 24
            continue
        x1, y1, x2, y2 = row["bbox"]
        box = (x1 * sx, y1 * sy + top, x2 * sx, y2 * sy + top)
        draw.rectangle(box, outline=color, width=3)
        draw.text((max(0, box[0]), max(top, box[1] - 22)), label, font=font, fill=color, stroke_width=1, stroke_fill="black")
    if not rows:
        draw.text((8, top + 8), "NO SUBMITTED RECORDS", font=font, fill="#fde047", stroke_width=1, stroke_fill="black")
    canvas.save(outpath, quality=90)


def _representatives(records: list[dict[str, Any]], center_sec: float) -> list[dict[str, Any]]:
    if len(records) <= _MAX_STILLS:
        return records
    selected = {min(range(len(records)), key=lambda index: abs(records[index]["t_sec"] - center_sec))}
    for number in range(_MAX_STILLS):
        selected.add(round(number * (len(records) - 1) / (_MAX_STILLS - 1)))
    # Keep the event frame plus evenly spread context, capped at eight.
    if len(selected) > _MAX_STILLS:
        center = min(selected, key=lambda index: abs(records[index]["t_sec"] - center_sec))
        removable = [index for index in selected if index not in (0, len(records) - 1, center)]
        selected.remove(min(removable, key=lambda index: abs(index - center)))
    return [records[index] for index in sorted(selected)]


def _playback_html(windows: list[dict[str, Any]], report: dict[str, Any]) -> str:
    payload = json.dumps(windows, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    render_errors = "".join(f"<li>{html.escape(item['video_id'])}: {html.escape(item['error'])}</li>" for item in report["render_errors"])
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tracking 失败片段回放</title><style>body{margin:24px auto;padding:0 20px;max-width:1100px;background:#f3f4f6;color:#111827;font:16px/1.65 system-ui,sans-serif}section{background:white;padding:20px;margin:20px 0;border-radius:12px}canvas{width:100%;height:auto;background:#111827}button,select{font:inherit;padding:5px 10px;margin-right:10px}input{width:100%}small{color:#4b5563}.status{margin:8px 0}.stills{display:flex;flex-wrap:wrap;gap:8px}.stills img{width:200px;height:auto}</style>
<h1>Tracking 诊断回放</h1><p>窗口使用连续原始帧与真实源时间间隔，画框在浏览器中绘制；这是本地 HTML 回放，没有生成带框 MP4。可暂停、逐帧检查或慢放。图片已经缩放，坐标来自显示方向原尺寸。</p>
<p>没有提交记录的帧会显示“未提交记录”，并不表示真实漏检；所有计数都不是准确率。窗口仅供定位问题，需人工确认狗、飞盘与动作。</p><ul>""" + render_errors + """</ul><main id="players"></main><script>
const windows=""" + payload + """;
const root=document.getElementById('players');
for(const w of windows){
 const section=document.createElement('section');root.appendChild(section);
 const title=document.createElement('h2');title.textContent=w.video_id+' · '+w.reason+' · '+w.start_sec.toFixed(3)+'–'+w.end_sec.toFixed(3)+' 秒';section.appendChild(title);
 const canvas=document.createElement('canvas');const ctx=canvas.getContext('2d');section.appendChild(canvas);
 const status=document.createElement('div');status.className='status';section.appendChild(status);
 const play=document.createElement('button');play.textContent='播放';section.appendChild(play);
 const prev=document.createElement('button');prev.textContent='上一帧';section.appendChild(prev);
 const next=document.createElement('button');next.textContent='下一帧';section.appendChild(next);
 const speed=document.createElement('select');for(const s of [0.25,0.5,1]){const o=document.createElement('option');o.value=s;o.textContent=s+'×';if(s===1)o.selected=true;speed.appendChild(o);}section.appendChild(speed);
 const slider=document.createElement('input');slider.type='range';slider.min=0;slider.max=w.frames.length-1;slider.step=1;section.appendChild(slider);
 let index=0,playing=false,timer=null,loadVersion=0;const cache=new Map();
 function load(i){if(!cache.has(i)){const im=new Image();const promise=new Promise((resolve,reject)=>{im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('图片加载失败'));});im.src=w.frames[i].path;cache.set(i,promise);}return cache.get(i);}
 async function draw(){const version=++loadVersion;const f=w.frames[index];slider.value=index;status.textContent='源帧 '+f.frame_id+' · '+f.t_sec.toFixed(3)+' 秒 · '+(index+1)+'/'+w.frames.length;try{const im=await load(index);if(version!==loadVersion)return;canvas.width=im.naturalWidth;canvas.height=im.naturalHeight+36;ctx.fillStyle='#111827';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(im,0,36);ctx.fillStyle='white';ctx.font='18px sans-serif';ctx.fillText(w.video_id+' | frame '+f.frame_id+' | '+f.t_sec.toFixed(3)+'s',10,25);let noteY=58;if(f.rows.length===0){ctx.fillStyle='#fde047';ctx.fillText('未提交记录',10,noteY);}for(const r of f.rows){const color=r.label==='dog'?'#22c55e':'#f97316';const label=r.label+' #'+r.track_id+(r.confidence===null?'':' '+r.confidence.toFixed(2));ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=3;ctx.font='18px sans-serif';if(r.bbox===null){ctx.fillText('MISSING: '+label,10,noteY);noteY+=24;}else{const [x1,y1,x2,y2]=r.bbox;const sx=im.naturalWidth/w.source_width,sy=im.naturalHeight/w.source_height;ctx.strokeRect(x1*sx,y1*sy+36,(x2-x1)*sx,(y2-y1)*sy);ctx.fillText(label,Math.max(0,x1*sx),Math.max(54,y1*sy+32));}}for(let j=index+1;j<Math.min(index+5,w.frames.length);j++)load(j).catch(()=>{});}catch(e){status.textContent+=' · '+e.message;stop();}}
 function stop(){playing=false;clearTimeout(timer);play.textContent='播放';}
 async function tick(){if(!playing)return;const started=performance.now();await draw();if(!playing)return;if(index>=w.frames.length-1){stop();return;}const delay=Math.max(1,(w.frames[index+1].t_sec-w.frames[index].t_sec)*1000/Number(speed.value)-(performance.now()-started));timer=setTimeout(()=>{index++;tick();},delay);}
 play.onclick=()=>{if(playing){stop();return;}if(index===w.frames.length-1)index=0;playing=true;play.textContent='暂停';tick();};
 prev.onclick=()=>{stop();index=Math.max(0,index-1);draw();};next.onclick=()=>{stop();index=Math.min(w.frames.length-1,index+1);draw();};slider.oninput=()=>{stop();index=Number(slider.value);draw();};speed.onchange=()=>{if(playing){clearTimeout(timer);tick();}};
 const stills=document.createElement('div');stills.className='stills';section.appendChild(stills);for(const path of w.stills){const a=document.createElement('a');a.href=path;a.target='_blank';const im=document.createElement('img');im.src=path;im.alt='代表帧';a.appendChild(im);stills.appendChild(a);}draw();
}
if(windows.length===0)root.textContent='没有可回放的动作窗口；请查看 report.json 的候选与渲染错误。';
</script></html>"""


def _cached_report(outdir: Path, content_hash: str, metrics: dict[str, Any], comparison: dict[str, Any], expected_windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Only reuse a complete package whose referenced media still verifies."""
    try:
        report = _read_json(outdir / "report.json")
        if not isinstance(report, dict) or report.get("content_hash") != content_hash or report.get("status") != "complete":
            return None
        if report.get("metrics") != metrics or report.get("comparison") != comparison or report.get("render_errors"):
            return None
        windows = report.get("windows")
        if not isinstance(windows, list) or len(windows) != len(expected_windows):
            return None
        for key in ("report", "metrics", "comparison", "failures", "summary", "playback"):
            asset = _pack_path(outdir, report["paths"][key])
            if not asset.is_file() or asset.stat().st_size == 0:
                return None
            if asset.suffix == ".json":
                _read_json(asset)
        for window, expected in zip(windows, expected_windows):
            if window.get("status") != "complete" or window.get("id") != expected["id"]:
                return None
            frames = window.get("frames", [])
            if not isinstance(frames, list) or [item["frame_id"] for item in frames] != [item["frame_id"] for item in expected["frame_records"]]:
                return None
            image_paths = [item["path"] for item in frames] + window.get("stills", [])
            if len(window.get("stills", [])) > _MAX_STILLS:
                return None
            for relative in image_paths:
                with Image.open(_pack_path(outdir, relative)) as image:
                    image.verify()
        return {**report, "cached": True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def review(root: str | Path, result_path: str | Path, tools: "Toolchain", previous_path: str | Path | None = None, processing_seconds: float | None = None) -> dict[str, Any]:
    """Build a review under ``root/reviews/<content hash>`` and return its report.

    ``previous_path`` is an earlier report.json or its containing review folder.
    ``processing_seconds`` is algorithm runtime supplied by the caller.
    """
    root = Path(root).resolve()
    result_path = Path(result_path).resolve()
    previous = Path(previous_path).resolve() if previous_path is not None else None
    if processing_seconds is not None and (not _finite(processing_seconds) or processing_seconds < 0):
        raise ValueError("processing_seconds 必须为非负有限数或 null")
    manifest = _read_json(root / "manifest.json")
    videos = _video_map(manifest)
    indexes: dict[str, list[dict[str, Any]]] = {}
    for video_id, video in videos.items():
        if video.get("status") == "complete":
            path = video.get("paths", {}).get("frame_index")
            indexes[video_id] = _read_json(_pack_path(root, path))
    rows = validate_results(_load_rows(result_path), manifest, indexes)
    _, positions, _ = _frame_maps(videos, indexes)
    source_signature, source_hashes = _source_signature(videos, indexes)
    coverage = _coverage(rows)
    metrics, candidates = _metrics_and_candidates(rows, videos, positions, float(processing_seconds) if processing_seconds is not None else None)
    comparison = _comparison(previous, source_signature, coverage, metrics)
    windows = _select_windows(root, videos, indexes, candidates)
    request = {"version": _VERSION, "source_signature": source_signature, "rows": rows, "comparison": comparison, "toolchain_version": getattr(tools, "version", None),
               "processing_seconds": processing_seconds, "windows": windows,
               "thresholds": {"low_confidence": _LOW_CONFIDENCE, "jump_diagonal_fraction": _JUMP_FRACTION, "jump_max_dt_sec": 0.25}}
    content_hash = _digest(request)
    outdir = (root / "reviews" / content_hash[:16]).resolve()
    if not outdir.is_relative_to(root):
        raise ValueError("review 输出目录超出资料包根目录")
    cached = _cached_report(outdir, content_hash, metrics, comparison, windows)
    if cached is not None:
        return cached
    outdir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": _VERSION, "content_hash": content_hash, "source_signature": source_signature,
              "source_hashes": source_hashes, "result_path": str(result_path), "output_dir": str(outdir), "report_path": str(outdir / "report.json"),
              "coverage": coverage, "coverage_summary": {key: value for key, value in coverage.items() if key != "entries"}, "metrics": metrics, "comparison": comparison, "cached": False, "status": "complete",
              "thresholds": request["thresholds"], "windows": [], "render_errors": [],
              "paths": {"report": "report.json", "metrics": "metrics.json", "comparison": "comparison.json", "failures": "failures.json", "summary": "summary.md", "playback": "playback.html"},
              "limitations": ["没有人工真值，不计算准确率或自动判定接盘。", "窗口每个动作视频最多两个，优先 missing、低置信度和跳变，再用已有运动候选补位。",
                              "轨迹 gap 仅表示源帧上未提交同轨迹记录，不等于真实漏检。", "回放使用连续原帧与源时间戳；HTML 在浏览器绘制框，没有生成带框 MP4。"]}
    row_lookup: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_lookup[(row["video_id"], row["frame_id"])].append(row)
    playback_windows = []
    from .media import extract_frames
    for window_number, window in enumerate(windows, 1):
        video = videos[window["video_id"]]
        window_dir = outdir / "windows" / f"{window_number:02d}"
        window_dir.mkdir(parents=True, exist_ok=True)
        public_window = {key: value for key, value in window.items() if key != "frame_records"}
        public_window["source_frame_count"] = len(window["frame_records"])
        public_window["stills"] = []
        public_window["frames"] = []
        try:
            extracted = extract_frames(video["source"], window["frame_records"], window_dir / "frames", tools, max_side=1280)
            if not isinstance(extracted, list) or len(extracted) != len(window["frame_records"]):
                raise ValueError("抽帧数量与窗口连续源帧数量不一致")
            by_frame = {item["frame_id"]: item for item in extracted}
            if len(by_frame) != len(extracted) or set(by_frame) != {item["frame_id"] for item in window["frame_records"]}:
                raise ValueError("抽帧 frame_id 与窗口源索引不一致")
            extracted = [by_frame[item["frame_id"]] for item in window["frame_records"]]
            for record in extracted:
                if not Path(record["path"]).resolve().is_relative_to(outdir):
                    raise ValueError("抽帧输出路径超出本次 review 目录")
            public_window["frames"] = [{"frame_id": record["frame_id"], "t_sec": record["t_sec"],
                                        "path": Path(record["path"]).relative_to(outdir).as_posix()} for record in extracted]
            for still_number, record in enumerate(_representatives(extracted, window["center_sec"]), 1):
                still_path = window_dir / f"overlay_{still_number:02d}_frame_{record['frame_id']}.jpg"
                _draw_still(record, video, row_lookup[(video["id"], record["frame_id"])], still_path)
                public_window["stills"].append(still_path.relative_to(outdir).as_posix())
            public_window["status"] = "complete"
            playback_windows.append({**public_window, "source_width": video["width"], "source_height": video["height"],
                                     "frames": [{"frame_id": record["frame_id"], "t_sec": record["t_sec"], "path": Path(record["path"]).relative_to(outdir).as_posix(),
                                                 "rows": row_lookup[(video["id"], record["frame_id"])]} for record in extracted]})
        except Exception as error:
            public_window["status"] = "failed"
            public_window["error"] = f"{type(error).__name__}: {error}"
            report["render_errors"].append({"video_id": video["id"], "window_id": window["id"], "error": public_window["error"]})
        report["windows"].append(public_window)
    if report["render_errors"]:
        report["status"] = "partial"
    _write_json(outdir / "failures.json", {"candidates": candidates, "selected_windows": report["windows"], "warning": "均为待人工确认的诊断候选，不是真值错误标签。"})
    _write_json(outdir / "metrics.json", metrics)
    _write_json(outdir / "comparison.json", comparison)
    _write_json(outdir / "report.json", report)
    (outdir / "playback.html").write_text(_playback_html(playback_windows, report), encoding="utf-8")
    lines = ["# Tracking 结果诊断", "", f"已严格验证 {len(rows)} 条记录；覆盖 {coverage['frame_label_count']} 个视频/帧/类别组合。", "",
             "无人工真值，本报告不计算准确率，也不判定接盘。", "",
             f"- 显式 missing 记录：{metrics['missing_record_count']}", f"- 低置信度 detected 记录（<0.4）：{metrics['low_confidence_record_count']}",
             f"- 同轨迹输出记录间隔：{metrics['trajectory_gap_count']}（不等于真实漏检）", f"- 短时间大位移候选：{metrics['jump_candidate_count']}",
             f"- 本地算法处理时长：{processing_seconds if processing_seconds is not None else '未提供'} 秒", "",
             f"上一版对比：{comparison['reason']}", ""]
    if comparison.get("warning"):
        lines.extend([comparison["warning"], ""])
    if comparison.get("deltas"):
        lines.extend(["| 诊断项 | 上一版 | 当前版 | 差值（当前−上一版） |", "|---|---:|---:|---:|"])
        for key, delta in comparison["deltas"].items():
            lines.append(f"| {key} | {delta['previous']} | {delta['current']} | {delta['delta']} |")
        lines.append("")
    completed = sum(item["status"] == "complete" for item in report["windows"])
    lines.extend([f"已生成 {completed} 个连续原帧窗口回放，每个窗口最多 8 张代表带框图。", "", "[打开本地带框回放](playback.html)", "",
                  "回放在浏览器中按真实源时间间隔展示抽取的连续帧并绘制框；没有生成叠加 MP4。未提交记录的帧不能据此判断漏检。", ""])
    if report["render_errors"]:
        lines.extend(["以下窗口渲染失败，指标仍已保存：", ""])
        lines.extend(f"- {item['video_id']}：{item['error']}" for item in report["render_errors"])
    (outdir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
