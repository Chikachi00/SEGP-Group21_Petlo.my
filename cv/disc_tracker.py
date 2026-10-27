"""Conservative disc tracklets, using source time and one-to-one association.

IDs describe local geometric continuity, not physical identity across occlusion.
Held and ground discs are retained; motion alone never labels a throw or catch.
"""
from dataclasses import dataclass, asdict
import math


def center(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class DiscSettings:
    confirm_samples: int = 2
    prediction_sec: float = .12
    identity_gap_sec: float = .35
    confidence: float = .25
    max_speed_diagonals_sec: float = 3.
    acceleration_diagonals_sec2: float = 8.
    gate_diagonal_fraction: float = .012
    ambiguity_margin: float = .12
    max_tracks: int = 16

    def __post_init__(self):
        for name in ('confirm_samples', 'max_tracks'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        for name, value in asdict(self).items():
            if name not in ('confirm_samples', 'max_tracks') and not finite(value):
                raise ValueError(f'{name} must be finite')
        if not 0 <= self.prediction_sec <= self.identity_gap_sec or self.identity_gap_sec <= 0:
            raise ValueError('Require 0 <= prediction <= identity gap, and identity gap > 0')
        if not 0 <= self.confidence <= 1 or not 0 <= self.ambiguity_margin < 1:
            raise ValueError('Invalid confidence or ambiguity margin')
        if self.max_speed_diagonals_sec <= 0 or self.acceleration_diagonals_sec2 < 0 or not 0 < self.gate_diagonal_fraction < 1:
            raise ValueError('Invalid motion gates')


@dataclass
class _Track:
    serial: int
    box: list
    last_time: float
    velocity: list
    samples: int = 1
    track_id: str | None = None
    missing: bool = False


class DiscTracker:
    def __init__(self, width, height, settings=None):
        if not finite(width) or not finite(height) or width <= 0 or height <= 0:
            raise ValueError('Positive finite display dimensions required')
        self.width, self.height = width, height
        self.diagonal = math.hypot(width, height)
        self.settings = settings or DiscSettings()
        self.previous_time = None
        self.tracks = []
        self.track_count = 0
        self.serial = 0

    def _candidates(self, detections):
        if not isinstance(detections, list):
            raise ValueError('detections must be a list')
        discs = []
        for detection in detections:
            if not isinstance(detection, dict):
                raise ValueError('Invalid detection')
            if detection.get('label') != 'disc':
                continue
            box, conf = detection.get('bbox'), detection.get('confidence')
            if not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box):
                raise ValueError('Invalid disc box')
            if not 0 <= box[0] < box[2] <= self.width or not 0 <= box[1] < box[3] <= self.height:
                raise ValueError('Disc box outside the oriented frame')
            if not finite(conf) or not 0 <= conf <= 1:
                raise ValueError('Invalid disc confidence')
            if conf >= self.settings.confidence:
                discs.append({'bbox': list(box), 'confidence': conf})
        # Contained crop duplicates can survive the detector's IoU suppression.
        # A spatially distinct second disc must remain available for its own ID.
        kept = []
        for d in sorted(discs, key=lambda v: (-v['confidence'], tuple(v['bbox']))):
            b = d['bbox']
            area = (b[2] - b[0]) * (b[3] - b[1])
            duplicate = False
            for previous in kept:
                a = previous['bbox']
                aa = (a[2] - a[0]) * (a[3] - a[1])
                intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                if intersection / min(area, aa) >= .85:
                    extent = max(math.hypot(a[2]-a[0], a[3]-a[1]), math.hypot(b[2]-b[0], b[3]-b[1]))
                    if math.dist(center(a), center(b)) <= .4 * extent:
                        duplicate = True
                        break
            if not duplicate:
                kept.append(d)
        return kept, len(discs), len(discs) - len(kept)

    def _predicted_box(self, track, now):
        delta = now - track.last_time
        dx, dy = [v * delta for v in track.velocity]
        b = track.box
        box = [max(0., min(self.width, b[0]+dx)), max(0., min(self.height, b[1]+dy)),
               max(0., min(self.width, b[2]+dx)), max(0., min(self.height, b[3]+dy))]
        return box if box[0] < box[2] and box[1] < box[3] else None

    def _cost(self, track, detection, now):
        dt = now - track.last_time
        b, a = detection['bbox'], track.box
        area_ratio = (b[2]-b[0]) * (b[3]-b[1]) / ((a[2]-a[0]) * (a[3]-a[1]))
        if not 1/8 <= area_ratio <= 8:
            return None
        displacement = math.dist(center(b), center(a))
        if displacement > self.settings.max_speed_diagonals_sec * self.diagonal * dt:
            return None
        expected = [p + v*dt for p, v in zip(center(a), track.velocity)]
        base = max(self.diagonal * self.settings.gate_diagonal_fraction, math.hypot(a[2]-a[0], a[3]-a[1]) * .6)
        if track.samples < 2:
            gate = base + self.settings.max_speed_diagonals_sec * self.diagonal * dt
        else:
            gate = base + .5 * self.settings.acceleration_diagonals_sec2 * self.diagonal * dt * dt
        distance = math.dist(center(b), expected)
        if distance > gate:
            return None
        return distance/gate + .05 * abs(math.log(area_ratio))

    def _associate(self, now, candidates):
        costs = {}
        track_costs = [[] for _ in self.tracks]
        candidate_costs = [[] for _ in candidates]
        for i, track in enumerate(self.tracks):
            for j, candidate in enumerate(candidates):
                cost = self._cost(track, candidate, now)
                if cost is not None:
                    costs[i, j] = cost
                    track_costs[i].append(cost)
                    candidate_costs[j].append(cost)
        ambiguous_tracks, ambiguous_candidates = set(), set()
        # Refuse both row and column near-ties; never send one detection to two IDs.
        # Build each row/column once rather than rescan every gated pair for it.
        for i, values in enumerate(track_costs):
            ranked = sorted(values)
            if len(ranked) > 1 and ranked[1] - ranked[0] < self.settings.ambiguity_margin:
                ambiguous_tracks.add(i)
        for j, values in enumerate(candidate_costs):
            ranked = sorted(values)
            if len(ranked) > 1 and ranked[1] - ranked[0] < self.settings.ambiguity_margin:
                ambiguous_candidates.add(j)
        matches, used = {}, set()
        for (i, j), cost in sorted(costs.items(), key=lambda item: (item[1], item[0])):
            if i not in matches and j not in used and i not in ambiguous_tracks and j not in ambiguous_candidates:
                matches[i] = j
                used.add(j)
        # Candidates already in any track gate do not become duplicate newborns
        # when a match is refused due to ambiguity or competition.
        gated = {j for _, j in costs}
        return matches, used, gated, ambiguous_tracks, ambiguous_candidates

    @staticmethod
    def _observation(track, state, bbox=None, confidence=None, prediction=None, reason=None, reacquired=False):
        return {'track_id': track.track_id, 'candidate_id': track.serial, 'state': state,
                'bbox': bbox, 'confidence': confidence, 'prediction_bbox': prediction,
                'tentative_bbox': list(track.box) if state == 'acquiring' else None,
                'reason': reason, 'reacquired': reacquired}

    def update(self, now, detections):
        if not finite(now) or now < 0 or self.previous_time is not None and now <= self.previous_time:
            raise ValueError('Source times must be finite, nonnegative and strictly increasing')
        candidates, raw_count, duplicate_count = self._candidates(detections)
        self.previous_time = now
        observations, retired = [], []
        for track in self.tracks:
            if now - track.last_time > self.settings.identity_gap_sec and track.track_id:
                retired.append(track.track_id)
                observations.append(self._observation(track, 'retired', reason='identity_gap_expired'))
        self.tracks = [t for t in self.tracks if now - t.last_time <= self.settings.identity_gap_sec]
        matches, used, gated, ambiguous_tracks, ambiguous_candidates = self._associate(now, candidates)
        survivors = []
        for i, track in enumerate(self.tracks):
            if i in matches:
                d = candidates[matches[i]]
                dt = now - track.last_time
                instant = [(b-a)/dt for a, b in zip(center(track.box), center(d['bbox']))]
                # Learn velocity immediately on the second sighting; thereafter
                # blend using elapsed time rather than an assumed frame rate.
                alpha = 1. if track.samples == 1 else 1 - math.exp(-dt/.035)
                track.velocity = [(1-alpha)*v + alpha*u for v, u in zip(track.velocity, instant)]
                was_missing = track.missing
                track.box, track.last_time = list(d['bbox']), now
                track.samples += 1
                track.missing = False
                if track.track_id is None and track.samples >= self.settings.confirm_samples:
                    self.track_count += 1
                    track.track_id = f'disc-{self.track_count:03d}'
                observations.append(self._observation(track, 'detected' if track.track_id else 'acquiring',
                    list(track.box) if track.track_id else None, d['confidence'] if track.track_id else None,
                    reacquired=bool(track.track_id and was_missing)))
                survivors.append(track)
            elif track.track_id:
                track.missing = True
                prediction = self._predicted_box(track, now) if now - track.last_time <= self.settings.prediction_sec else None
                reason = 'ambiguous_association' if i in ambiguous_tracks or any(j in ambiguous_candidates for j in gated if self._cost(track, candidates[j], now) is not None) else 'no_candidate_in_gate' if candidates else 'no_disc_detection'
                observations.append(self._observation(track, 'predicted' if prediction else 'lost', prediction=prediction, reason=reason))
                survivors.append(track)
            # Unconfirmed tracks must have consecutive compatible observations.
        self.tracks = survivors
        overflow = 0
        for j, d in enumerate(candidates):
            if j in used or j in gated:
                continue
            if len(self.tracks) >= self.settings.max_tracks:
                overflow += 1
                continue
            self.serial += 1
            track = _Track(self.serial, list(d['bbox']), now, [0., 0.])
            if self.settings.confirm_samples == 1:
                self.track_count += 1
                track.track_id = f'disc-{self.track_count:03d}'
            self.tracks.append(track)
            observations.append(self._observation(track, 'detected' if track.track_id else 'acquiring',
                list(track.box) if track.track_id else None, d['confidence'] if track.track_id else None))
        return {'tracks': observations, 'retired_track_ids': retired, 'raw_disc_count': raw_count,
                'candidate_count': len(candidates), 'duplicate_count': duplicate_count,
                'unassigned_count': len(candidates) - len(used) - sum(t.last_time == now and t.samples == 1 for t in self.tracks),
                'capacity_rejections': overflow}


def contract_rows(video_id, record, state):
    observed = [t for t in state['tracks'] if t['track_id']]
    if not observed:
        return [{'video_id': video_id, 'frame_id': record['frame_id'], 't_sec': record['t_sec'],
                 'label': 'disc', 'track_id': 'disc-unassigned', 'bbox': None, 'confidence': None, 'status': 'missing'}]
    return [{'video_id': video_id, 'frame_id': record['frame_id'], 't_sec': record['t_sec'],
             'label': 'disc', 'track_id': t['track_id'], 'bbox': t['bbox'], 'confidence': t['confidence'],
             'status': 'detected' if t['state'] == 'detected' else 'missing'} for t in observed]
