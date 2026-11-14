"""Select high-value, timestamped frames for detector fine-tuning from a prepared packet.

Frames are chosen from signals the pipeline already computes (motion peaks, detector
gaps near confident disc detections, low-confidence discs) plus a small uniform sample
for background diversity, then extracted at native resolution with their real frame IDs.
Static, redundant frames are limited by a minimum time gap and per-reason quotas.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1

# Share of the per-video budget by reason; unused quota rolls into the next reason.
QUOTAS = (("motion", .40), ("disc_gap", .25), ("low_confidence_disc", .15), ("uniform", .20))
UNIFORM_CAP = .25


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


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def motion_peaks(motion, smoothing=.25):
    """Frame IDs ranked by locally smoothed motion score, highest first."""
    if not motion:
        return []
    times = [m["t_sec"] for m in motion]
    prefix = [0.]
    for m in motion:
        prefix.append(prefix[-1] + m["motion_score"])
    half = smoothing / 2
    scored = []
    for index, m in enumerate(motion):
        left = bisect.bisect_left(times, m["t_sec"] - half)
        right = bisect.bisect_right(times, m["t_sec"] + half)
        score = (prefix[right] - prefix[left]) / max(1, right - left)
        if score > 1e-8:
            scored.append((-score, m["t_sec"], m["frame_id"]))
    scored.sort()
    return [frame_id for _, _, frame_id in scored]


def detector_candidates(rows, near_sec=.5, confident=.5, floor=.25):
    """Return {'disc_gap': [...], 'low_confidence_disc': [...]} frame ID lists.

    disc_gap: no disc at/above `floor`, but a confident disc within +-near_sec
    (likely misses: the most useful frames to label).
    low_confidence_disc: best disc confidence in [floor, confident).
    """
    best = {}
    for row in rows:
        confidences = [d["confidence"] for d in row["detections"] if d["label"] == "disc"]
        best[row["frame_id"]] = max(confidences, default=0.)
    times = {row["frame_id"]: row["t_sec"] for row in rows}
    anchors = sorted(times[f] for f, c in best.items() if c >= confident)
    gap, low = [], []
    for frame_id, confidence in best.items():
        if confidence >= confident:
            continue
        if confidence >= floor:
            low.append(frame_id)
            continue
        t = times[frame_id]
        index = bisect.bisect_left(anchors, t - near_sec)
        if index < len(anchors) and anchors[index] <= t + near_sec:
            gap.append(frame_id)
    return {"disc_gap": sorted(gap), "low_confidence_disc": sorted(low)}


def _even(items, count):
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(k * (len(items) - 1) / (count - 1))] for k in range(count)]


class _Selection:
    def __init__(self, times, min_gap):
        self.times, self.min_gap = times, min_gap
        self.chosen = {}          # frame_id -> reason
        self._sorted = []         # selected times

    def allowed(self, frame_id):
        if frame_id in self.chosen:
            return False
        t = self.times[frame_id]
        i = bisect.bisect_left(self._sorted, t)
        near = self._sorted[max(0, i - 1):i + 1]
        return all(abs(t - other) >= self.min_gap - 1e-9 for other in near)

    def take(self, candidates, quota, reason, ranked):
        """Take up to `quota` frames; ranked pools keep their order, others spread evenly."""
        pool = [f for f in candidates if f in self.times]
        order = pool if ranked else _even(sorted(pool, key=self.times.get), len(pool))
        if not ranked and len(order) > quota:
            # Spread across the pool first, then fall back to the remainder in time order.
            spread = _even(sorted(pool, key=self.times.get), quota)
            order = spread + [f for f in sorted(pool, key=self.times.get) if f not in set(spread)]
        taken = 0
        for frame_id in order:
            if taken >= quota:
                break
            if self.allowed(frame_id):
                self.chosen[frame_id] = reason
                bisect.insort(self._sorted, self.times[frame_id])
                taken += 1
        return taken


def select_frames(frame_index, motion, detector_rows=None, max_frames=150, min_gap_sec=.4, uniform_step_sec=5.):
    """Pure selection. Returns {frame_id: reason}."""
    if max_frames < 1 or min_gap_sec < 0:
        raise ValueError("max_frames must be positive and min_gap_sec non-negative")
    times = {r["frame_id"]: r["t_sec"] for r in frame_index}
    selection = _Selection(times, min_gap_sec)
    pools = {"motion": (motion_peaks(motion), True)}
    found = detector_candidates(detector_rows) if detector_rows else {"disc_gap": [], "low_confidence_disc": []}
    pools["disc_gap"] = (found["disc_gap"], False)
    pools["low_confidence_disc"] = (found["low_confidence_disc"], False)
    ordered = sorted(frame_index, key=lambda r: r["t_sec"])
    uniform, next_t = [], ordered[0]["t_sec"] if ordered else 0.
    for record in ordered:
        if record["t_sec"] >= next_t - 1e-9:
            uniform.append(record["frame_id"])
            next_t = record["t_sec"] + uniform_step_sec
    pools["uniform"] = (uniform, False)
    carry = 0
    for reason, share in QUOTAS:
        quota = math.ceil(max_frames * share) + carry
        if reason == "uniform":
            quota = min(quota, math.ceil(max_frames * UNIFORM_CAP))
        quota = min(quota, max_frames - len(selection.chosen))
        candidates, ranked = pools[reason]
        taken = selection.take(candidates, quota, reason, ranked)
        carry = max(0, quota - taken) if reason != "uniform" else 0
    return dict(sorted(selection.chosen.items()))


def load_detector_rows(path, video):
    path = Path(path)
    report = read_json(path.with_suffix(".json"))
    if report.get("status") != "complete" or report.get("video_id") != video["id"] \
            or report.get("source_sha256") != video["source_sha256"]:
        raise ValueError(f"Detector run {path.name} does not match prepared video {video['id']}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not rows or any(r.get("video_id") != video["id"] for r in rows):
        raise ValueError(f"Detector rows in {path.name} do not belong to {video['id']}")
    return rows, report.get("model_sha256")


def build(pack, session, output_dir, video_ids=None, detections=None, max_frames=150, min_gap_sec=.4,
          ffmpeg_dir=None, include_context=False):
    if __package__:
        from .video_tools.media import Toolchain, extract_frames  # local import: needs numpy/PIL
    else:
        from video_tools.media import Toolchain, extract_frames
    pack, output = Path(pack).resolve(), Path(output_dir).resolve()
    if not session or any(c in session for c in '\\/:*?"<>| ') or session.startswith("."):
        raise ValueError("Session must be a simple name without spaces or path characters")
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Use a new session name.")
    manifest = read_json(pack / "manifest.json")
    videos = {v["id"]: v for v in manifest["videos"]}
    wanted = video_ids or [v["id"] for v in manifest["videos"]
                           if v["status"] == "complete" and (v["role"] == "action" or include_context)]
    if not wanted:
        raise ValueError("No usable videos in the packet")
    for video_id in wanted:
        if video_id not in videos or videos[video_id]["status"] != "complete":
            raise ValueError(f"Video is missing or failed in the packet: {video_id}")
    detector_by_video = {}
    for path in detections or []:
        report = read_json(Path(path).with_suffix(".json"))
        video = videos.get(report.get("video_id"))
        if video is None:
            raise ValueError(f"Detector run {path} refers to a video not in the packet")
        detector_by_video[video["id"]] = load_detector_rows(path, video)
    tools = Toolchain.discover(ffmpeg_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".training-{uuid.uuid4().hex}"
    (staging / "frames").mkdir(parents=True)
    try:
        entries, summary = [], {}
        for video_id in wanted:
            video = videos[video_id]
            source = Path(video["source"])
            if sha256(source) != video["source_sha256"]:
                raise ValueError(f"Source changed since prepare: {video_id}")
            index = read_json(pack / video["paths"]["frame_index"])
            motion = read_json(pack / video["paths"]["motion_index"])
            rows = detector_by_video.get(video_id, (None, None))[0]
            chosen = select_frames(index, motion, rows, max_frames, min_gap_sec)
            records = [index[f] for f in chosen]
            scratch = staging / "_extract" / video_id
            images = extract_frames(source, records, scratch, tools, max_side=None)
            for image in images:
                name = f"{video_id}__f{image['frame_id']:06d}.jpg"
                shutil.move(image["path"], staging / "frames" / name)
                entries.append({"image": f"frames/{name}", "video_id": video_id, "session": session,
                                "frame_id": image["frame_id"], "pts_sec": image["pts_sec"], "t_sec": image["t_sec"],
                                "reason": chosen[image["frame_id"]], "width": image["source_width"],
                                "height": image["source_height"], "source_sha256": video["source_sha256"],
                                "camera": video.get("camera"), "role": video.get("role")})
            counts = {}
            for reason in chosen.values():
                counts[reason] = counts.get(reason, 0) + 1
            summary[video_id] = {"frames": len(images), "by_reason": counts,
                                 "detector_guided": rows is not None}
        shutil.rmtree(staging / "_extract")
        entries.sort(key=lambda e: (e["video_id"], e["frame_id"]))
        (staging / "manifest.json").write_text(json.dumps(
            {"schema_version": SCHEMA_VERSION, "session": session, "pack": str(pack),
             "parameters": {"max_frames_per_video": max_frames, "min_gap_sec": min_gap_sec},
             "detector_model_sha256": {k: v[1] for k, v in detector_by_video.items()},
             "summary": summary, "images": entries}, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        _rename_with_retry(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"output": str(output), "images": len(entries), "summary": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True, help="Prepared packet (python -m cv.video_tools prepare)")
    parser.add_argument("--session", required=True, help="Name of this recording session; also the dataset split group")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--video-id", action="append", help="Repeat to select videos (default: all action videos)")
    parser.add_argument("--detections", type=Path, action="append",
                        help="detect_disc_video.py JSONL (repeat per video) to find disc gaps and low-confidence frames")
    parser.add_argument("--max-frames", type=int, default=150, help="Budget per video (default 150)")
    parser.add_argument("--min-gap-sec", type=float, default=.4)
    parser.add_argument("--include-context", action="store_true", help="Also use Setup/context videos")
    parser.add_argument("--ffmpeg-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or PROJECT / "data" / "training" / args.session
    try:
        result = build(args.pack, args.session, output, args.video_id, args.detections, args.max_frames,
                       args.min_gap_sec, args.ffmpeg_dir, args.include_context)
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"Frame selection failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
