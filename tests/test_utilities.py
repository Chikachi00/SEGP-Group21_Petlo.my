"""Lightweight tests for deterministic utility functions."""

import argparse
from pathlib import Path
import unittest

from cv.detect_video import default_output_path, display_label, probability
from cv.extract_frames import (
    default_output_directory,
    frame_filename,
    positive_integer,
)
from cv.video_info import calculate_duration


class VideoInformationTests(unittest.TestCase):
    """Tests for metadata calculations that do not require a real video."""

    def test_calculate_duration(self) -> None:
        self.assertEqual(calculate_duration(900, 30.0), 30.0)

    def test_zero_fps_has_no_duration(self) -> None:
        self.assertIsNone(calculate_duration(900, 0.0))

    def test_negative_fps_has_no_duration(self) -> None:
        self.assertIsNone(calculate_duration(900, -1.0))


class FrameExtractionUtilityTests(unittest.TestCase):
    """Tests for frame extraction parameters and filenames."""

    def test_frame_filename_uses_source_frame_number(self) -> None:
        self.assertEqual(frame_filename(30), "frame_000030.jpg")

    def test_negative_frame_number_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            frame_filename(-1)

    def test_positive_frame_interval_is_accepted(self) -> None:
        self.assertEqual(positive_integer("30"), 30)

    def test_zero_frame_interval_is_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_integer("0")

    def test_default_frame_directory_uses_video_stem(self) -> None:
        self.assertEqual(
            default_output_directory(Path("data/raw/session.mp4")),
            Path("data/frames/session"),
        )


class DetectionUtilityTests(unittest.TestCase):
    """Tests for detection command parameters and display naming."""

    def test_frisbee_is_displayed_as_disc(self) -> None:
        self.assertEqual(display_label("frisbee"), "disc")

    def test_default_detection_output_uses_video_stem(self) -> None:
        self.assertEqual(
            default_output_path(Path("data/raw/session.mp4")),
            Path("outputs/session_detected.mp4"),
        )

    def test_probability_accepts_boundary_values(self) -> None:
        self.assertEqual(probability("0"), 0.0)
        self.assertEqual(probability("1"), 1.0)

    def test_probability_rejects_out_of_range_value(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            probability("1.1")


if __name__ == "__main__":
    unittest.main()

