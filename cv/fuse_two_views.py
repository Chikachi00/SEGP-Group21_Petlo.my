"""Fuse two fixed-camera v3 event runs using an estimated clock offset, not event order.

Unlike fuse_throw_events_v3.py this works for any front/side pair: it estimates the
time offset between the cameras from the events themselves (or accepts a manual hint
such as a clap/flash reference), matches events one-to-one inside a tolerance, keeps
events seen by only one view, and refuses to claim a combined result when the cameras
cannot be aligned. All outcomes remain unverified candidates.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import statistics

if __package__:
    from .audio_sync import AudioSyncSettings, estimate_audio_offset
    from .build_throw_statistics import sha256, summarize
    from .joint_analysis import center, diagonal
else:
    from audio_sync import AudioSyncSettings, estimate_audio_offset
    from build_throw_statistics import sha256, summarize
    from joint_analysis import center, diagonal

DECISIVE = ("catch_candidate", "ground_pickup_candidate", "miss_candidate")
VIEWS = ("front", "side")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class FusionSettings:
    tolerance_sec: float = .6      # max residual between a pair's time difference and the offset
    max_offset_sec: float = 2.0    # largest camera clock offset considered for event-only estimation
    min_pairs: int = 2             # matched pairs needed to trust an estimated offset
    offset_hint_sec: float | None = None  # side clock minus front clock, from a sync reference
    use_audio_sync: bool = True    # prefer GCC-PHAT audio sync when source videos are available

    def __post_init__(self):
        if not _finite(self.tolerance_sec) or self.tolerance_sec <= 0:
            raise ValueError("tolerance_sec must be positive and finite")
        if not _finite(self.max_offset_sec) or self.max_offset_sec <= 0:
            raise ValueError("max_offset_sec must be positive and finite")
        if type(self.min_pairs) is not int or self.min_pairs < 1:
            raise ValueError("min_pairs must be a positive integer")
        if self.offset_hint_sec is not None and not _finite(self.offset_hint_sec):
            raise ValueError("offset_hint_sec must be finite")
        if not isinstance(self.use_audio_sync, bool):
            raise ValueError("use_audio_sync must be a boolean")


def _time(event, use_release):
    release = event.get("release_evidence")
    return release["departure_sec"] if use_release and release else event["start_sec"]


def pair_delta(front, side):
    """Side-minus-front time of the same landmark; release time only if both views saw it."""
    both = bool(front.get("release_evidence")) and bool(side.get("release_evidence"))
    return _time(side, both) - _time(front, both)


def match(front, side, offset, tolerance):
    """Greedy one-to-one matching by smallest residual. Returns [(i, j, residual)]."""
    candidates = sorted(
        (abs(pair_delta(f, s) - offset), i, j)
        for i, f in enumerate(front) for j, s in enumerate(side))
    used_front, used_side, pairs = set(), set(), []
    for residual, i, j in candidates:
        if residual <= tolerance + 1e-9 and i not in used_front and j not in used_side:
            used_front.add(i)
            used_side.add(j)
            pairs.append((i, j, residual))
    return pairs


def interval_gap(front, side, offset):
    """Time gap between front interval and offset-mapped side interval (0 if overlapping)."""
    mapped_start = side["start_sec"] - offset
    mapped_end = side["end_sec"] - offset
    return max(0.0, front["start_sec"] - mapped_end, mapped_start - front["end_sec"])


def match_synced(front, side, offset, tolerance):
    """One-to-one matching for audio-verified clocks using interval overlap or endpoint tolerance."""
    candidates = []
    for i, f in enumerate(front):
        for j, s in enumerate(side):
            start_res = abs(pair_delta(f, s) - offset)
            gap = interval_gap(f, s, offset)
            if start_res <= tolerance + 1e-9 or gap <= tolerance + 1e-9:
                f_mid = 0.5 * (f["start_sec"] + f["end_sec"])
                s_mid = 0.5 * (s["start_sec"] + s["end_sec"]) - offset
                mid_res = abs(f_mid - s_mid)
                candidates.append((gap, mid_res, start_res, i, j))
    candidates.sort()
    used_front, used_side, pairs = set(), set(), []
    for gap, mid_res, start_res, i, j in candidates:
        if i not in used_front and j not in used_side:
            used_front.add(i)
            used_side.add(j)
            pairs.append((i, j, round(min(gap, start_res), 4) if gap > 0 else round(mid_res, 4)))
    return pairs


def estimate_offset(front, side, settings):
    """Try every plausible pairwise difference; keep the offset explaining the most events."""
    deltas = {round(pair_delta(f, s), 6) for f in front for s in side}
    best, best_score = None, None
    for offset in sorted(deltas):
        if abs(offset) > settings.max_offset_sec:
            continue
        pairs = match(front, side, offset, settings.tolerance_sec)
        score = (len(pairs), -sum(r for _, _, r in pairs), -abs(offset))
        if best_score is None or score > best_score:
            best, best_score = offset, score
    if best is None:
        return None, []
    pairs = match(front, side, best, settings.tolerance_sec)
    if pairs:
        # Refine with the median of the matched pairs, keeping it only if no pair is lost.
        refined = statistics.median(pair_delta(front[i], side[j]) for i, j, _ in pairs)
        again = match(front, side, refined, settings.tolerance_sec)
        if len(again) >= len(pairs) and abs(refined) <= settings.max_offset_sec:
            best, pairs = refined, again
    return best, pairs


def fuse_outcome(front_outcome, side_outcome):
    """Return (outcome, agreement). A disagreement between decisive outcomes stays uncertain."""
    present = [o for o in (front_outcome, side_outcome) if o is not None]
    votes = {o for o in present if o in DECISIVE}
    if len(votes) > 1:
        return "uncertain", "conflict"
    if not votes:
        return "uncertain", "no_evidence"
    outcome = next(iter(votes))
    if len(present) == 2 and front_outcome == side_outcome:
        return outcome, "corroborated"
    return outcome, "single_view_evidence"


def _row(front, side, offset, residual):
    outcome, agreement = fuse_outcome(front["predicted_outcome"] if front else None,
                                      side["predicted_outcome"] if side else None)
    interval = lambda e: [e["start_sec"], e["end_sec"]] if e else None
    return {"sample_throw_id": None,
            "views": "both" if front and side else "front" if front else "side",
            "front_throw_id": front["throw_id"] if front else None,
            "side_throw_id": side["throw_id"] if side else None,
            "front_outcome": front["predicted_outcome"] if front else None,
            "side_outcome": side["predicted_outcome"] if side else None,
            "front_source_time_sec": interval(front), "side_source_time_sec": interval(side),
            "outcome": outcome, "agreement": agreement, "conflict": agreement == "conflict",
            "match_residual_sec": residual}


def _sort_key(row, offset):
    if row["front_source_time_sec"]:
        return row["front_source_time_sec"][0]
    return row["side_source_time_sec"][0] - (offset or 0.)


def _cross_view_carry(joint_frames, window_start, window_end, *, min_carry_sec=0.25, near_dog_diagonals=0.12):
    """Look for sustained dog+disc co-motion in the complementary view's mapped window."""
    if not joint_frames:
        return None
    # Group observed near-dog disc points by (disc_id, dog_id) inside the mapped window.
    by_pair = {}
    for frame in joint_frames:
        t = frame.get("t_sec")
        if t is None or t < window_start - 0.1 or t > window_end + 1.5:
            continue
        dog = frame.get("dog") or {}
        dog_box = dog.get("bbox") if dog.get("state") == "detected" else None
        dog_id = dog.get("track_id")
        if dog_box is None or not dog_id:
            continue
        for d in frame.get("discs") or []:
            if d.get("state") != "detected" or d.get("bbox") is None:
                continue
            gap = d.get("gap_to_dog_diagonals")
            if gap is None or gap > near_dog_diagonals:
                continue
            key = (d.get("disc_id"), dog_id)
            by_pair.setdefault(key, []).append({
                "t_sec": t, "frame_id": frame.get("frame_id"),
                "bbox": d["bbox"], "dog_bbox": dog_box,
                "measurement_source": d.get("measurement_source"),
            })
    for (disc_id, dog_id), seq in by_pair.items():
        seq.sort(key=lambda p: p["t_sec"])
        # Split on observation gaps > 0.2s
        groups_list, current = [], []
        for p in seq:
            if current and p["t_sec"] - current[-1]["t_sec"] > 0.2 + 1e-9:
                groups_list.append(current)
                current = []
            current.append(p)
        if current:
            groups_list.append(current)
        for g in groups_list:
            if len(g) < 3 or g[-1]["t_sec"] - g[0]["t_sec"] < min_carry_sec - 1e-9:
                continue
            anchors = [p for p in g if p["measurement_source"] in ("saved_detector", "local_yolo")]
            if len(anchors) < 2:
                continue
            first, last = anchors[0], anchors[-1]
            if last["t_sec"] - first["t_sec"] < min_carry_sec * 0.5:
                continue
            scale = diagonal(last["dog_bbox"])
            disc_v = [b - a for a, b in zip(center(first["bbox"]), center(last["bbox"]))]
            dog_v = [b - a for a, b in zip(center(first["dog_bbox"]), center(last["dog_bbox"]))]
            if min(math.hypot(*disc_v), math.hypot(*dog_v)) < 0.08 * scale:
                continue
            if math.dist(disc_v, dog_v) > 0.30 * scale:
                continue
            return {
                "outcome": "catch_candidate",
                "evidence_type": "cross_view_sustained_co_motion",
                "disc_id": disc_id, "dog_id": dog_id,
                "start_frame": first["frame_id"], "end_frame": last["frame_id"],
                "start_sec": first["t_sec"], "end_sec": last["t_sec"],
                "observed_samples": len(g), "model_observed_samples": len(anchors),
                "mapped_window_sec": [round(window_start, 3), round(window_end + 1.5, 3)],
            }
    return None


def _apply_cross_view_evidence(rows, offset, front_joint, side_joint):
    """For uncertain non-conflicting events, check the synced other view's joint observations."""
    if offset is None or (not front_joint and not side_joint):
        return 0
    resolved = 0
    for row in rows:
        if row["outcome"] != "uncertain" or row["conflict"]:
            continue
        evidence = None
        source_view = None
        if row["front_source_time_sec"] and side_joint:
            s_start = row["front_source_time_sec"][0] + offset
            s_end = row["front_source_time_sec"][1] + offset
            evidence = _cross_view_carry(side_joint, s_start, s_end)
            source_view = "side"
        if evidence is None and row["side_source_time_sec"] and front_joint:
            f_start = row["side_source_time_sec"][0] - offset
            f_end = row["side_source_time_sec"][1] - offset
            evidence = _cross_view_carry(front_joint, f_start, f_end)
            source_view = "front"
        if evidence is not None:
            row["outcome"] = evidence["outcome"]
            row["agreement"] = "cross_view_evidence"
            row["cross_view_evidence"] = {"source_view": source_view, **evidence}
            resolved += 1
    return resolved


def fuse_events(front, side, settings=None, *, audio_sync=None, front_joint=None, side_joint=None,
                front_duration=None, side_duration=None):
    """Pure function: two lists of v3 event candidates -> sync report and combined rows."""
    cfg = settings or FusionSettings()
    sync = {"status": "unreliable", "offset_sec": None, "matched_pairs": 0, "front_events": len(front),
            "side_events": len(side), "max_residual_sec": None, "reason": None}
    if audio_sync is not None:
        sync["audio_sync"] = audio_sync
        if audio_sync.get("warning"):
            sync["warning"] = audio_sync["warning"]
    pairs, offset = [], None
    if cfg.offset_hint_sec is not None:
        offset = cfg.offset_hint_sec
        pairs = match(front, side, offset, cfg.tolerance_sec)
        sync["status"] = "manual"
    elif audio_sync is not None and audio_sync.get("status") == "verified" and _finite(audio_sync.get("offset_sec")):
        offset = float(audio_sync["offset_sec"])
        pairs = match_synced(front, side, offset, cfg.tolerance_sec)
        sync["status"] = "audio_verified"
    elif not front or not side:
        sync["reason"] = "A view has no event candidates, so the cameras cannot be aligned."
    else:
        offset, pairs = estimate_offset(front, side, cfg)
        needed = min(cfg.min_pairs, len(front), len(side))
        if not pairs:
            sync["reason"] = "No events line up within the tolerance at any plausible offset."
        elif len(pairs) < needed:
            sync["reason"] = f"Only {len(pairs)} matched pair(s); at least {needed} required."
        else:
            sync["status"] = "weak" if min(len(front), len(side)) == 1 else "estimated"

    if sync["status"] == "unreliable":
        # Never merge views that could not be aligned: report the better-covered view alone.
        primary = "side" if len(side) > len(front) else "front"
        rows = [_row(e if primary == "front" else None, e if primary == "side" else None, None, None)
                for e in (front if primary == "front" else side)]
        sync["fallback_view"] = primary
    else:
        sync.update(offset_sec=offset, matched_pairs=len(pairs),
                    max_residual_sec=max((r for _, _, r in pairs), default=None))
        rows = [_row(front[i], side[j], offset, r) for i, j, r in pairs]
        matched_front, matched_side = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
        rows += [_row(e, None, offset, None) for i, e in enumerate(front) if i not in matched_front]
        rows += [_row(None, e, offset, None) for j, e in enumerate(side) if j not in matched_side]
        if sync["status"] in ("audio_verified", "manual", "estimated"):
            sync["cross_view_resolved"] = _apply_cross_view_evidence(rows, offset, front_joint, side_joint)
        if offset is not None and (front_duration is not None or side_duration is not None):
            for row in rows:
                if row["views"] == "front" and side_duration is not None:
                    f_int = row["front_source_time_sec"]
                    if f_int[1] + offset < 0.0 or f_int[0] + offset > side_duration:
                        row["outside_other_view_coverage"] = True
                elif row["views"] == "side" and front_duration is not None:
                    s_int = row["side_source_time_sec"]
                    if s_int[1] - offset < 0.0 or s_int[0] - offset > front_duration:
                        row["outside_other_view_coverage"] = True
    rows.sort(key=lambda r: _sort_key(r, offset))
    for number, row in enumerate(rows, 1):
        row["sample_throw_id"] = f"event-{number:03d}"
    return sync, rows


def _load_joint_frames(joint_dir):
    if joint_dir is None:
        return None
    path = Path(joint_dir).resolve() / "joint.jsonl"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_run(directory, expected_view):
    """Validate one complete per-view v3 run and return its identity and events."""
    folder = Path(directory).resolve()
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8-sig"))
    if summary.get("status") != "complete":
        raise ValueError(f"The {expected_view} event run is not complete")
    if summary.get("provenance", {}).get("camera") != "tripod":
        raise ValueError(f"The {expected_view} run must come from a fixed tripod camera")
    for name, digest in summary.get("artifact_sha256", {}).items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Modified or missing {expected_view} artifact: {name}")
    payload = json.loads((folder / "events-v3.json").read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 3 or payload.get("video_id") != summary.get("video_id"):
        raise ValueError(f"Unexpected {expected_view} v3 event file")
    events = payload["event_candidates"]
    for event in events:
        if not isinstance(event.get("throw_id"), str) or not _finite(event.get("start_sec")) \
                or not _finite(event.get("end_sec")) or "predicted_outcome" not in event:
            raise ValueError(f"Invalid {expected_view} event record")
    return {"video_id": summary["video_id"], "source_sha256": summary["provenance"]["source_sha256"],
            "source": summary.get("provenance", {}).get("source"),
            "cache_key": summary["cache_key"], "events": sorted(events, key=lambda e: e["start_sec"])}


def run(front_dir, side_dir, output_dir, settings=None, *,
        front_video=None, side_video=None, front_joint_dir=None, side_joint_dir=None,
        ffmpeg_dir=None, audio_settings=None, front_duration=None, side_duration=None):
    cfg = settings or FusionSettings()
    front, side = load_run(front_dir, "front"), load_run(side_dir, "side")
    if front["source_sha256"] == side["source_sha256"]:
        raise ValueError("Front and side runs analyse the same source video")
    audio_sync = None
    if cfg.use_audio_sync and cfg.offset_hint_sec is None:
        f_vid = Path(front_video) if front_video else (Path(front["source"]) if front.get("source") else None)
        s_vid = Path(side_video) if side_video else (Path(side["source"]) if side.get("source") else None)
        if f_vid and s_vid and f_vid.is_file() and s_vid.is_file():
            audio_sync = estimate_audio_offset(f_vid, s_vid, ffmpeg_dir=ffmpeg_dir, settings=audio_settings)
    front_joint = _load_joint_frames(front_joint_dir)
    side_joint = _load_joint_frames(side_joint_dir)
    sync, rows = fuse_events(front["events"], side["events"], cfg,
                             audio_sync=audio_sync, front_joint=front_joint, side_joint=side_joint,
                             front_duration=front_duration, side_duration=side_duration)
    payload = {"schema_version": 1, "algorithm": "throw-events-v3 two-view time-offset fusion",
               "source_sha256": {"front": front["source_sha256"], "side": side["source_sha256"]},
               "video_ids": {"front": front["video_id"], "side": side["video_id"]},
               "settings": asdict(cfg), "sync": sync, "results": rows,
               "limitations": ["Outcomes are unverified algorithm candidates, not measured accuracy.",
                               "Camera alignment is a single constant offset; drift or dropped footage is not modelled.",
                               "Audio sync over outdoor camera distances (~15-20 m) includes ~0.04-0.06 s acoustic travel delay.",
                               "Events seen in one view only carry single-view evidence unless corroborated via synced joint observations.",
                               "If synchronisation is unreliable only one view's events are reported."]}
    summarize(payload)  # fail early if the statistics builder would reject these rows
    payload["cache_key"] = hashlib.sha256(json.dumps(
        {"front": front["cache_key"], "side": side["cache_key"], "settings": asdict(cfg),
         "audio_sync": audio_sync, "code": sha256(Path(__file__))}, sort_keys=True).encode()).hexdigest()
    output = Path(output_dir).resolve()
    target = output / "fused-results.json"
    if target.exists():
        raise ValueError("Fusion output already exists; choose a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front-dir", type=Path, required=True)
    parser.add_argument("--side-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--front-video", type=Path, help="Optional front source video for audio GCC-PHAT sync")
    parser.add_argument("--side-video", type=Path, help="Optional side source video for audio GCC-PHAT sync")
    parser.add_argument("--front-joint-dir", type=Path, help="Optional front joint-analysis dir for cross-view evidence")
    parser.add_argument("--side-joint-dir", type=Path, help="Optional side joint-analysis dir for cross-view evidence")
    parser.add_argument("--ffmpeg-dir", type=Path)
    parser.add_argument("--no-audio-sync", action="store_true", help="Disable audio GCC-PHAT sync and use event timing only")
    parser.add_argument("--offset-hint", type=float, help="Side clock minus front clock in seconds (e.g. from a clap)")
    parser.add_argument("--tolerance", type=float, default=.6)
    parser.add_argument("--max-offset", type=float, default=2.0)
    parser.add_argument("--min-pairs", type=int, default=2)
    args = parser.parse_args()
    try:
        result = run(args.front_dir, args.side_dir, args.output_dir,
                     FusionSettings(args.tolerance, args.max_offset, args.min_pairs, args.offset_hint, not args.no_audio_sync),
                     front_video=args.front_video, side_video=args.side_video,
                     front_joint_dir=args.front_joint_dir, side_joint_dir=args.side_joint_dir,
                     ffmpeg_dir=args.ffmpeg_dir)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Two-view fusion failed: {exc}\n")
    print(json.dumps({"sync": result["sync"], "events": len(result["results"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
