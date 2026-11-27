import unittest
import numpy as np

from cv.audio_sync import AudioSyncSettings, estimate_audio_offset_signals, gcc_phat_offset
from cv.detect_disc_video import Detection, band_crop_grid, has_local_motion, merge_discs
from cv.disc_tracker import DiscTracker
from cv.fuse_two_views import FusionSettings, fuse_events
from cv.throw_events import _filter_edge_bystanders


def _shifted_signal(base, offset_sec, sr=8000, noise_std=0.05, seed=0):
    rng = np.random.default_rng(seed)
    shift = int(round(offset_sec * sr))
    out = np.zeros_like(base)
    if shift >= 0:
        if shift < base.size:
            out[shift:] = base[:base.size - shift]
    else:
        cut = -shift
        if cut < base.size:
            out[:base.size - cut] = base[cut:]
    return out + rng.normal(0.0, noise_std, size=base.size).astype(np.float32)


class AudioSyncTests(unittest.TestCase):
    def setUp(self):
        self.sr = 8000
        rng = np.random.default_rng(42)
        self.base = rng.normal(0.0, 1.0, size=self.sr * 20).astype(np.float32)

    def test_recovers_negative_and_positive_offsets_accurately(self):
        for true_offset in (-3.84, 1.25):
            side = _shifted_signal(self.base, true_offset, self.sr, noise_std=0.1, seed=7)
            result = estimate_audio_offset_signals(self.base, side, AudioSyncSettings(sample_rate=self.sr))
            self.assertEqual(result["status"], "verified")
            self.assertAlmostEqual(result["offset_sec"], true_offset, delta=0.01)
            self.assertLess(result["half_diff_sec"], 0.05)

    def test_rejects_spliced_signal_with_disagreeing_halves(self):
        half = self.base.size // 2
        s1 = _shifted_signal(self.base[:half], -1.0, self.sr, noise_std=0.05, seed=1)
        s2 = _shifted_signal(self.base[half:], -4.5, self.sr, noise_std=0.05, seed=2)
        spliced = np.concatenate([s1, s2])
        result = estimate_audio_offset_signals(self.base, spliced, AudioSyncSettings(sample_rate=self.sr))
        self.assertEqual(result["status"], "unreliable")
        self.assertEqual(result["warning"], "possible_splice_or_frame_drop")
        self.assertIn("disagree", result["reason"])

    def test_rejects_uncorrelated_noise_and_silence(self):
        rng = np.random.default_rng(99)
        noise = rng.normal(0.0, 1.0, size=self.base.size).astype(np.float32)
        self.assertEqual(estimate_audio_offset_signals(self.base, noise)["status"], "unreliable")
        silence = np.zeros_like(self.base)
        self.assertEqual(estimate_audio_offset_signals(self.base, silence)["status"], "unreliable")

    def test_gcc_phat_rejects_too_short_input(self):
        with self.assertRaises(ValueError):
            gcc_phat_offset(np.array([0.0]), np.array([0.0, 1.0]))


class CrossViewFusionTests(unittest.TestCase):
    def _event(self, number, start, end, outcome):
        return {
            "throw_id": f"throw-{number:03d}", "start_sec": start, "end_sec": end,
            "predicted_outcome": outcome, "release_evidence": {"departure_sec": start + 0.1},
        }

    def test_audio_verified_sync_pairs_large_offset_events(self):
        front = [self._event(1, 6.0, 8.2, "catch_candidate")]
        side = [self._event(1, 2.16, 4.36, "catch_candidate")]
        audio = {"status": "verified", "method": "audio_gcc_phat", "offset_sec": -3.84, "snr": 24.0}
        sync, rows = fuse_events(front, side, audio_sync=audio)
        self.assertEqual(sync["status"], "audio_verified")
        self.assertAlmostEqual(sync["offset_sec"], -3.84, places=3)
        self.assertEqual(sync["matched_pairs"], 1)
        self.assertEqual(rows[0]["agreement"], "corroborated")

    def test_audio_verified_sync_pairs_overlapping_intervals_with_late_start(self):
        # Front misses early flight (starts 7.83s), Side starts 4.73s; mapped Side is [6.53..8.53]
        front = [self._event(1, 7.83, 8.53, "catch_candidate")]
        side = [self._event(1, 4.73, 6.73, "catch_candidate")]
        audio = {"status": "verified", "method": "audio_gcc_phat", "offset_sec": -1.80, "snr": 7.0}
        sync, rows = fuse_events(front, side, audio_sync=audio)
        self.assertEqual(sync["status"], "audio_verified")
        self.assertEqual(sync["matched_pairs"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["views"], "both")
        self.assertEqual(rows[0]["agreement"], "corroborated")

    def test_cross_view_joint_resolves_front_uncertain_edge_exit(self):
        front = [self._event(1, 6.0, 8.2, "uncertain")]
        side = []
        audio = {"status": "verified", "method": "audio_gcc_phat", "offset_sec": -1.80, "snr": 12.0}
        # Side joint frames show sustained dog+disc carry at side t = 6.5..7.1s (mapped from front 8.2 + (-1.8) = 6.4s)
        side_joint = []
        for idx in range(10):
            t = 6.4 + idx * 0.08
            x = 500.0 + idx * 25.0
            side_joint.append({
                "frame_id": 190 + idx, "t_sec": t,
                "dog": {"track_id": "dog-001", "state": "detected", "bbox": [x, 400.0, x + 120.0, 500.0]},
                "discs": [{
                    "disc_id": "disc-001", "state": "detected",
                    "bbox": [x + 95.0, 420.0, x + 125.0, 445.0],
                    "gap_to_dog_diagonals": 0.0,
                    "measurement_source": "saved_detector",
                }],
            })
        sync, rows = fuse_events(front, side, audio_sync=audio, side_joint=side_joint)
        self.assertEqual(sync["status"], "audio_verified")
        self.assertEqual(sync["cross_view_resolved"], 1)
        self.assertEqual(rows[0]["outcome"], "catch_candidate")
        self.assertEqual(rows[0]["agreement"], "cross_view_evidence")
        self.assertEqual(rows[0]["cross_view_evidence"]["source_view"], "side")


class BandCropGridTests(unittest.TestCase):
    def test_equal_sized_tiles_cover_horizontal_band(self):
        tiles = band_crop_grid(2560, 1440, cols=4, y_range=(0.15, 0.85), overlap=0.2)
        self.assertEqual(len(tiles), 4)
        widths = {x2 - x1 for x1, _, x2, _ in tiles}
        heights = {y2 - y1 for _, y1, _, y2 in tiles}
        self.assertEqual(len(widths), 1)
        self.assertEqual(len(heights), 1)
        self.assertEqual(tiles[0][0], 0)
        self.assertEqual(tiles[-1][2], 2560)
        self.assertLess(next(iter(widths)), 1000)

    def test_rejects_invalid_band_parameters(self):
        with self.assertRaises(ValueError):
            band_crop_grid(2560, 1440, cols=1)
        with self.assertRaises(ValueError):
            band_crop_grid(2560, 1440, y_range=(0.8, 0.2))


class MotionGateTests(unittest.TestCase):
    def test_static_box_rejected_and_moving_coloured_disc_accepted(self):
        bg = np.full((120, 200, 3), (40, 120, 40), dtype=np.uint8)
        cur = bg.copy()
        cur[50:62, 80:105] = (200, 60, 220)  # pink disc against green grass
        self.assertFalse(has_local_motion(cur, bg, [10, 10, 40, 30]))
        self.assertTrue(has_local_motion(cur, bg, [78, 48, 107, 64]))

    def test_disc_tracker_accepts_motion_gated_low_confidence_only(self):
        tracker = DiscTracker(200, 120)
        # Unmarked low-conf disc is ignored
        s1 = tracker.update(0.1, [{"label": "disc", "bbox": [10., 10., 30., 25.], "confidence": 0.14, "origin": "tile"}])
        self.assertEqual(s1["candidate_count"], 0)
        # Motion-gated low-conf disc is accepted
        s2 = tracker.update(0.2, [{"label": "disc", "bbox": [10., 10., 30., 25.], "confidence": 0.14, "origin": "tile_motion"}])
        self.assertEqual(s2["candidate_count"], 1)

    def test_stationary_background_disc_flagged_and_cleared_on_motion(self):
        tracker = DiscTracker(400, 300)
        box = [100., 100., 120., 112.]
        for i in range(25):
            state = tracker.update(i * 0.1, [{"label": "disc", "bbox": box, "confidence": 0.8}])
        tracks = [t for t in state["tracks"] if t["track_id"]]
        self.assertTrue(tracks[0]["stationary_background"])
        # Once picked up and moved smoothly past 1.5 diagonals, flag clears immediately
        for step in range(1, 5):
            dx = step * 12.0
            state2 = tracker.update(2.4 + step * 0.1, [{"label": "disc", "bbox": [100. + dx, 100., 120. + dx, 112.], "confidence": 0.8}])
        tracks2 = [t for t in state2["tracks"] if t["track_id"]]
        self.assertFalse(tracks2[0]["stationary_background"])

    def test_outside_other_view_coverage_marked_on_trailing_single_view_event(self):
        front = []
        side = [{"throw_id": "throw-001", "start_sec": 58.0, "end_sec": 60.0,
                 "predicted_outcome": "uncertain", "release_evidence": None}]
        audio = {"status": "verified", "method": "audio_gcc_phat", "offset_sec": -0.1, "snr": 25.0}
        _, rows = fuse_events(front, side, audio_sync=audio, front_duration=55.2, side_duration=63.3)
        self.assertTrue(rows[0].get("outside_other_view_coverage"))

    def test_merge_discs_drops_truncated_tile_seam_half_but_keeps_distinct_disc(self):
        full_disc = Detection([1175., 536., 1221., 571.], 0.93, "frisbee", "tile")
        seam_half = Detection([1205., 539., 1221., 570.], 0.57, "frisbee", "tile")
        other_disc = Detection([1583., 946., 1622., 960.], 0.84, "frisbee", "tile")
        merged = merge_discs([full_disc, seam_half, other_disc])
        self.assertEqual(len(merged), 2)
        self.assertEqual({round(d.bbox[0]) for d in merged}, {1175, 1583})

    def test_filter_edge_bystanders_keeps_handler_and_drops_edge_passerby(self):
        handler = [1800., 800., 1900., 1100.]
        bystander = [3700., 900., 3830., 1200.]
        self.assertEqual(_filter_edge_bystanders([handler, bystander], 3840), [handler])
        # Single person near edge is never dropped
        self.assertEqual(_filter_edge_bystanders([bystander], 3840), [bystander])
        # Dominant handler standing at left edge (e.g. Sample7 Side) is preserved when another person is in background
        left_handler = [80., 600., 150., 800.]
        bg_person = [1900., 600., 1960., 780.]
        self.assertEqual(_filter_edge_bystanders([left_handler, bg_person], 2560, dominant_bins={0}), [left_handler, bg_person])

    def test_merge_discs_deduplicates_tiled_dog_boxes(self):
        full_dog = Detection([500., 700., 620., 790.], 0.88, "dog", "tile")
        seam_dog = Detection([580., 710., 620., 785.], 0.61, "dog", "tile")
        merged = merge_discs([full_dog, seam_dog])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0].confidence, 0.88)


if __name__ == "__main__":
    unittest.main()
