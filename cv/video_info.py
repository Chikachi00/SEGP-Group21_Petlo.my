"""Print basic metadata for a local video file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import NamedTuple

import cv2


class VideoInformation(NamedTuple):
    """Metadata read from a video container."""

    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float | None


def calculate_duration(frame_count: int, fps: float) -> float | None:
    """Return the approximate duration, or ``None`` when FPS is unavailable."""

    if fps <= 0:
        return None
    return frame_count / fps


def validate_video_path(video_path: Path) -> None:
    """Raise a clear error when the input path is not a readable file path."""

    if not video_path.exists():
        raise ValueError(f"Video file does not exist: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Video path is not a file: {video_path}")


def read_video_information(video_path: Path) -> VideoInformation:
    """Open a video and read its basic container metadata."""

    validate_video_path(video_path)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video file: {video_path}")

    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()

    return VideoInformation(
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=calculate_duration(frame_count, fps),
    )


def print_video_information(video_path: Path, information: VideoInformation) -> None:
    """Print video metadata in a compact, human-readable format."""

    print("Video Information")
    print("-----------------")
    print(f"File: {video_path.name}")
    print(f"Resolution: {information.width} x {information.height}")
    print(f"FPS: {information.fps:.2f}")
    print(f"Frames: {information.frame_count}")
    if information.duration_seconds is None:
        print("Duration: unavailable because the reported FPS is zero")
    else:
        print(f"Duration: {information.duration_seconds:.2f} seconds")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="Print the resolution, FPS, frame count, and duration of a video."
    )
    parser.add_argument("video", type=Path, help="Path to a local video file.")
    return parser


def main() -> int:
    """Run the command-line interface."""

    args = build_parser().parse_args()
    try:
        information = read_video_information(args.video)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print_video_information(args.video, information)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

