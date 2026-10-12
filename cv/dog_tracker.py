"""Conservative single-dog association using actual source timestamps.

This is a small constant-velocity tracker, not a multi-object/re-identification
model. Predictions never become detections or refresh the measurement clock.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class TrackingSettings:
    confirm_samples: int = 3
    initialization_gap_sec: float = .15
    prediction_sec: float = .25
    identity_gap_sec: float = .75
    confidence: float = .25
    gate_scale: float = 1.25
    ambiguity_margin: float = .10

    def __post_init__(self):
        if isinstance(self.confirm_samples, bool) or not isinstance(self.confirm_samples, int) or self.confirm_samples < 1:
            raise ValueError("confirm_samples must be a positive integer")
        for name, value in asdict(self).items():
            if name != "confirm_samples" and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite")
        if not 0 < self.initialization_gap_sec or not 0 <= self.prediction_sec <= self.identity_gap_sec or self.identity_gap_sec <= 0:
            raise ValueError("Require initialization_gap > 0 and 0 <= prediction <= identity_gap")
        if not 0 <= self.confidence <= 1 or self.gate_scale <= 0 or not 0 <= self.ambiguity_margin < 1:
            raise ValueError("Invalid confidence or association settings")


def center(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def iou(a, b):
    intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ab = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (aa + ab - intersection)


class DogTracker:
    def __init__(self, width, height, settings=None):
        if width <= 0 or height <= 0:
            raise ValueError("Positive display dimensions required")
        self.width, self.height = width, height
        self.settings = settings or TrackingSettings()
        self.previous_time = None
        self.last_time = None
        self.last_box = None
        self.velocity = [0., 0.]
        self.track_id = None
        self.track_count = 0
        self.tentative = None
        self.tentative_time = None
        self.tentative_count = 0
        self.missing_since_measurement = False

    def _prediction(self, now):
        dt = now - self.last_time
        dx, dy = [v * dt for v in self.velocity]
        b = self.last_box
        box = [max(0., min(self.width, b[0] + dx)), max(0., min(self.height, b[1] + dy)),
               max(0., min(self.width, b[2] + dx)), max(0., min(self.height, b[3] + dy))]
        return box if box[0] < box[2] and box[1] < box[3] else None

    def _match(self, candidates, reference, gap):
        if reference is None:
            return None, "prediction_outside_frame"
        diag = math.hypot(reference[2] - reference[0], reference[3] - reference[1])
        gate = max(math.hypot(self.width, self.height) * .01, diag * self.settings.gate_scale)
        # A bounded allowance for uncertainty; prolonged absence must not allow
        # an arbitrary detection on the other side of the image to take this ID.
        gate *= 1 + min(gap, self.settings.identity_gap_sec)
        origin = center(reference)
        area = (reference[2] - reference[0]) * (reference[3] - reference[1])
        ranked = []
        for detection in candidates:
            box = detection["bbox"]
            ratio = (box[2] - box[0]) * (box[3] - box[1]) / area
            distance = math.dist(center(box), origin)
            if 1 / 3 <= ratio <= 3 and distance <= gate:
                cost = distance / gate + .15 * abs(math.log(ratio)) + .15 * (1 - iou(box, reference))
                ranked.append((cost, detection))
        ranked.sort(key=lambda item: item[0])
        if not ranked:
            return None, "no_candidate_in_gate" if candidates else "no_dog_detection"
        if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < self.settings.ambiguity_margin:
            return None, "ambiguous_candidates"
        return ranked[0][1], None

    def update(self, now, detections):
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now) or now < 0 or self.previous_time is not None and now <= self.previous_time:
            raise ValueError("Source times must be finite, nonnegative and strictly increasing")
        candidates = []
        for detection in detections:
            if detection.get("label") != "dog":
                continue
            box, confidence = detection.get("bbox"), detection.get("confidence")
            if not isinstance(box, list) or len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
                raise ValueError("Invalid dog box")
            if not 0 <= box[0] < box[2] <= self.width or not 0 <= box[1] < box[3] <= self.height:
                raise ValueError("Dog box outside the oriented display frame")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid dog confidence")
            if confidence >= self.settings.confidence:
                candidates.append(detection)
        self.previous_time = now
        retired = None
        if self.track_id and now - self.last_time > self.settings.identity_gap_sec:
            retired = self.track_id
            self.track_id = None
            self.last_box = None
            self.velocity = [0., 0.]
            self.tentative = None
            self.tentative_count = 0
        measured = predicted = tentative_box = None
        confidence = None
        reason = None
        reacquired = False
        if self.track_id:
            gap = now - self.last_time
            predicted = self._prediction(now)
            matched, reason = self._match(candidates, predicted, gap)
            if matched:
                measured, confidence = list(matched["bbox"]), matched["confidence"]
                before, after = center(self.last_box), center(measured)
                alpha = 1 - math.exp(-gap / .12)
                self.velocity = [(1 - alpha) * old + alpha * (new - prev) / gap
                                 for old, new, prev in zip(self.velocity, after, before)]
                reacquired = self.missing_since_measurement
                self.last_box, self.last_time = measured, now
                self.missing_since_measurement = False
                predicted = None
                state = "detected"
            else:
                self.missing_since_measurement = True
                if gap <= self.settings.prediction_sec and predicted:
                    state = "predicted"
                else:
                    predicted = None
                    state = "lost"
        else:
            matched = None
            if self.tentative and now - self.tentative_time <= self.settings.initialization_gap_sec:
                matched, reason = self._match(candidates, self.tentative, now - self.tentative_time)
            if not matched:
                self.tentative_count = 0
                self.tentative = None
                ranked = sorted(candidates, key=lambda d: d["confidence"], reverse=True)
                if ranked and (len(ranked) == 1 or ranked[0]["confidence"] - ranked[1]["confidence"] >= self.settings.ambiguity_margin):
                    matched = ranked[0]
                elif ranked:
                    reason = "ambiguous_initialization"
            if matched:
                self.tentative = list(matched["bbox"])
                self.tentative_time = now
                self.tentative_count += 1
                tentative_box = self.tentative
                state = "acquiring"
                if self.tentative_count >= self.settings.confirm_samples:
                    self.track_count += 1
                    self.track_id = f"dog-{self.track_count:03d}"
                    self.last_box, self.last_time = self.tentative, now
                    self.velocity = [0., 0.]
                    self.missing_since_measurement = False
                    measured, confidence = list(self.last_box), matched["confidence"]
                    state = "detected"
                    tentative_box = None
            else:
                state = "searching"
                reason = reason or "no_dog_detection"
        return {"track_id": self.track_id, "state": state, "bbox": measured,
                "confidence": confidence, "prediction_bbox": predicted,
                "tentative_bbox": tentative_box, "reason": reason,
                "reacquired": reacquired, "retired_track_id": retired,
                "candidate_count": len(candidates)}


def contract_row(video_id, record, observation):
    """The review schema deliberately has no predicted detection status."""
    return {"video_id": video_id, "frame_id": record["frame_id"], "t_sec": record["t_sec"],
            "label": "dog", "track_id": observation["track_id"] or "dog-unassigned",
            "bbox": observation["bbox"], "confidence": observation["confidence"],
            "status": "detected" if observation["state"] == "detected" else "missing"}
