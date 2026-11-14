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
    from .build_throw_statistics import sha256, summarize
else:
    from build_throw_statistics import sha256, summarize

DECISIVE = ("catch_candidate", "ground_pickup_candidate", "miss_candidate")
VIEWS = ("front", "side")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class FusionSettings:
    tolerance_sec: float = .6      # max residual between a pair's time difference and the offset
    max_offset_sec: float = 2.0    # largest camera clock offset considered
    min_pairs: int = 2             # matched pairs needed to trust an estimated offset
    offset_hint_sec: float | None = None  # side clock minus front clock, from a sync reference

    def __post_init__(self):
        if not _finite(self.tolerance_sec) or self.tolerance_sec <= 0:
            raise ValueError("tolerance_sec must be positive and finite")
        if not _finite(self.max_offset_sec) or self.max_offset_sec <= 0:
            raise ValueError("max_offset_sec must be positive and finite")
        if type(self.min_pairs) is not int or self.min_pairs < 1:
            raise ValueError("min_pairs must be a positive integer")
        if self.offset_hint_sec is not None and not _finite(self.offset_hint_sec):
            raise ValueError("offset_hint_sec must be finite")


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


def fuse_events(front, side, settings=None):
    """Pure function: two lists of v3 event candidates -> sync report and combined rows."""
    cfg = settings or FusionSettings()
    sync = {"status": "unreliable", "offset_sec": None, "matched_pairs": 0, "front_events": len(front),
            "side_events": len(side), "max_residual_sec": None, "reason": None}
    pairs, offset = [], None
    if cfg.offset_hint_sec is not None:
        offset = cfg.offset_hint_sec
        pairs = match(front, side, offset, cfg.tolerance_sec)
        sync["status"] = "manual"
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
    rows.sort(key=lambda r: _sort_key(r, offset))
    for number, row in enumerate(rows, 1):
        row["sample_throw_id"] = f"event-{number:03d}"
    return sync, rows


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
            "cache_key": summary["cache_key"], "events": sorted(events, key=lambda e: e["start_sec"])}


def run(front_dir, side_dir, output_dir, settings=None):
    cfg = settings or FusionSettings()
    front, side = load_run(front_dir, "front"), load_run(side_dir, "side")
    if front["source_sha256"] == side["source_sha256"]:
        raise ValueError("Front and side runs analyse the same source video")
    sync, rows = fuse_events(front["events"], side["events"], cfg)
    payload = {"schema_version": 1, "algorithm": "throw-events-v3 two-view time-offset fusion",
               "source_sha256": {"front": front["source_sha256"], "side": side["source_sha256"]},
               "video_ids": {"front": front["video_id"], "side": side["video_id"]},
               "settings": asdict(cfg), "sync": sync, "results": rows,
               "limitations": ["Outcomes are unverified algorithm candidates, not measured accuracy.",
                               "Camera alignment is a single constant offset; drift or dropped footage is not modelled.",
                               "Events seen in one view only carry single-view evidence.",
                               "If synchronisation is unreliable only one view's events are reported."]}
    summarize(payload)  # fail early if the statistics builder would reject these rows
    payload["cache_key"] = hashlib.sha256(json.dumps(
        {"front": front["cache_key"], "side": side["cache_key"], "settings": asdict(cfg),
         "code": sha256(Path(__file__))}, sort_keys=True).encode()).hexdigest()
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
    parser.add_argument("--offset-hint", type=float, help="Side clock minus front clock in seconds (e.g. from a clap)")
    parser.add_argument("--tolerance", type=float, default=.6)
    parser.add_argument("--max-offset", type=float, default=2.0)
    parser.add_argument("--min-pairs", type=int, default=2)
    args = parser.parse_args()
    try:
        result = run(args.front_dir, args.side_dir, args.output_dir,
                     FusionSettings(args.tolerance, args.max_offset, args.min_pairs, args.offset_hint))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Two-view fusion failed: {exc}\n")
    print(json.dumps({"sync": result["sync"], "events": len(result["results"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
