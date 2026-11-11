"""Compare optimized CV searches with exhaustive, ordered window searches."""
import math
import random
import unittest

from cv.disc_tracker import DiscTracker
from cv.joint_analysis import center, diagonal
from cv.throw_events import EventSettings, carry_evidence, groups
from cv.throw_events_v3 import _relative_carry


def exhaustive_carry(sequence, contact, cfg, relative=False):
    """Small-input oracle that deliberately rescans every candidate window."""
    start = contact[0]['t_sec']
    after = [p for p in sequence if start <= p['t_sec'] <= start + cfg.post_contact_sec
             and (relative or p['dog_bbox'] is not None)]
    for group in groups(after, lambda p: p['dog_id'] == contact[0]['dog_id']
                        and p['dog_bbox'] is not None and p['dog_gap'] <= cfg.near_dog_diagonals,
                        cfg.observation_gap_sec, True):
        if relative:
            group = [p for p in group if p['measurement_source'] in ('saved_detector', 'local_yolo')]
            ranges = ((left, right) for left in range(len(group)) for right in range(left + 2, len(group)))
        else:
            ranges = ((left, right) for right in range(4, len(group)) for left in range(right - 3))
        for left, right in ranges:
            window = group[left:right + 1]
            first, last = window[0], window[-1]
            if last['t_sec'] - first['t_sec'] < cfg.min_carry_sec - 1e-9:
                continue
            anchors = [p for p in window if p['measurement_source'] in ('saved_detector', 'local_yolo')]
            if not relative and (len(anchors) < 2 or anchors[-1]['t_sec'] - anchors[0]['t_sec'] < cfg.min_carry_sec * .5):
                continue
            disc_v = [b - a for a, b in zip(center(first['bbox']), center(last['bbox']))]
            dog_v = [b - a for a, b in zip(center(first['dog_bbox']), center(last['dog_bbox']))]
            if relative:
                positions = []
                for p in window:
                    b, dog = p['bbox'], p['dog_bbox']
                    width, height = dog[2] - dog[0], dog[3] - dog[1]
                    if width <= 0 or height <= 0:
                        break
                    positions.append(((b[0] + b[2] - dog[0] - dog[2]) * .5 / width,
                                      (b[1] + b[3] - dog[1] - dog[3]) * .5 / height))
                if len(positions) != len(window):
                    continue
                sx = max(p[0] for p in positions) - min(p[0] for p in positions)
                sy = max(p[1] for p in positions) - min(p[1] for p in positions)
                disc_move = math.dist(center(first['bbox']), center(last['bbox']))
                dog_move = math.dist(center(first['dog_bbox']), center(last['dog_bbox']))
                if sx > .25 or sy > .65 or min(disc_move, dog_move) < .08 * diagonal(first['dog_bbox']):
                    continue
            elif min(math.hypot(*disc_v), math.hypot(*dog_v)) < .1 * diagonal(last['dog_bbox']) or math.dist(disc_v, dog_v) > .25 * diagonal(last['dog_bbox']):
                continue
            result = {'start_frame': first['frame_id'], 'end_frame': last['frame_id'],
                      'start_sec': first['t_sec'], 'end_sec': last['t_sec'], 'dog_id': first['dog_id'],
                      'observed_samples': len(window), 'model_observed_samples': len(anchors),
                      'relative_displacement_px': math.dist(disc_v, dog_v), 'mouth_localized': False}
            if relative:
                result.update(relative_position_x_spread=sx, relative_position_y_spread=sy,
                              relative_displacement_px=disc_move - dog_move,
                              evidence_type='disc_stays_in_dog_box_during_motion')
            return result
    return None


def carry_points(seed, count=45):
    rng = random.Random(seed)
    points = []
    now = 0.
    speed = rng.choice((0., 40., 200.))
    noisy = rng.choice((False, False, True))
    for i in range(count):
        now += rng.choice((.012, .025, .04, .14))
        x = 100 + speed * now
        dx = rng.uniform(-40, 40) if noisy else 0.
        dog = [x, 100., x + 80., 200.]
        if rng.random() < .05:
            dog = None
        points.append({'frame_id': 200 + i, 't_sec': now, 'bbox': [x + dx, 140., x + dx + 12., 148.],
                       'dog_bbox': dog, 'dog_id': 'dog-1' if rng.random() > .05 else 'dog-2',
                       'dog_gap': .02 if rng.random() > .08 else .2,
                       'measurement_source': rng.choice(('saved_detector', 'local_visual', 'local_yolo'))})
    return points


class CountedPoint(dict):
    reads = None

    def __getitem__(self, key):
        self.reads[key] = self.reads.get(key, 0) + 1
        return super().__getitem__(key)


class CarrySearchOptimizationTests(unittest.TestCase):
    def test_v2_and_v3_match_exhaustive_window_order_and_evidence(self):
        cfg = EventSettings()
        outcomes = {False: set(), True: set()}
        for seed in range(150):
            sequence = carry_points(seed)
            # Test multiple contact positions, nonuniform times and fragmented groups.
            for start in (0, 10, 20):
                contact = [sequence[start]]
                for relative, analyze in ((False, carry_evidence), (True, _relative_carry)):
                    with self.subTest(seed=seed, start=start, relative=relative):
                        expected = exhaustive_carry(sequence, contact, cfg, relative)
                        self.assertEqual(analyze(sequence, contact, cfg), expected)
                        outcomes[relative].add(expected is not None)
        self.assertEqual(outcomes, {False: {False, True}, True: {False, True}})

    def test_v2_rejected_dense_windows_read_model_sources_once(self):
        sequence = carry_points(0, 180)
        reads = {}
        for i, point in enumerate(sequence):
            point.update(t_sec=i / 240, dog_bbox=[100., 100., 180., 200.],
                         bbox=[110., 140., 122., 148.], dog_id='dog-1', dog_gap=.02,
                         measurement_source='saved_detector')
        sequence = [CountedPoint(p) for p in sequence]
        for point in sequence:
            point.reads = reads
        self.assertIsNone(carry_evidence(sequence, sequence[:1], EventSettings()))
        self.assertLessEqual(reads['measurement_source'], len(sequence))

    def test_v3_rejected_dense_windows_avoid_cubic_geometry_reads(self):
        sequence = carry_points(0, 100)
        reads = {}
        for i, point in enumerate(sequence):
            point.update(t_sec=i / 120, dog_bbox=[100., 100., 180., 200.],
                         bbox=[110., 140., 122., 148.], dog_id='dog-1', dog_gap=.02,
                         measurement_source='saved_detector')
        sequence = [CountedPoint(p) for p in sequence]
        for point in sequence:
            point.reads = reads
        self.assertIsNone(_relative_carry(sequence, sequence[:1], EventSettings()))
        self.assertLess(reads['bbox'], 4 * len(sequence) ** 2)


class DiscAssociationOptimizationTests(unittest.TestCase):
    def test_matches_gates_and_both_ambiguity_directions_match_exhaustive_search(self):
        rng = random.Random(1907)
        tracker = DiscTracker(1000, 600)
        for _ in range(100):
            tracker.tracks = list(range(rng.randrange(20)))
            candidates = list(range(rng.randrange(20)))
            costs = {(i, j): rng.choice((.1, .2, .22, .4, .8))
                     for i in tracker.tracks for j in candidates if rng.random() > .3}
            tracker._cost = lambda i, j, now: costs.get((i, j))
            ambiguous_tracks, ambiguous_candidates = set(), set()
            for indices, ambiguous, axis in ((tracker.tracks, ambiguous_tracks, 0),
                                              (candidates, ambiguous_candidates, 1)):
                for index in indices:
                    ranked = sorted(cost for pair, cost in costs.items() if pair[axis] == index)
                    if len(ranked) > 1 and ranked[1] - ranked[0] < tracker.settings.ambiguity_margin:
                        ambiguous.add(index)
            matches, used = {}, set()
            for (i, j), cost in sorted(costs.items(), key=lambda item: (item[1], item[0])):
                if i not in matches and j not in used and i not in ambiguous_tracks and j not in ambiguous_candidates:
                    matches[i] = j
                    used.add(j)
            expected = matches, used, {j for _, j in costs}, ambiguous_tracks, ambiguous_candidates
            self.assertEqual(tracker._associate(1., candidates), expected)


if __name__ == '__main__':
    unittest.main()
