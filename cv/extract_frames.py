"""Extract frames from a local video at a fixed interval."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import cv2


DEFAULT_FRAME_INTERVAL = 30


def positive_integer(value: str) -> int:
    """Convert a command-line value to an integer greater than zero."""

    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("The frame interval must be an integer.") from error
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError("The frame interval must be greater than zero.")
    return parsed_value


def frame_filename(frame_number: int) -> str:
    """Return the deterministic JPEG name for a zero-based source frame number."""

    if frame_number < 0:
        raise ValueError("The frame number cannot be negative.")
    return f"frame_{frame_number:06d}.jpg"


def default_output_directory(video_path: Path) -> Path:
    """Return the default output directory for an input video."""

    return Path("data") / "frames" / video_path.stem


def validate_video_path(video_path: Path) -> None:
    """Raise a clear error when the input is missing or is not a file."""

    if not video_path.exists():
        raise ValueError(f"Video file does not exist: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Video path is not a file: {video_path}")


def extract_frames(
    video_path: Path, output_directory: Path, every_n_frames: int
) -> tuple[int, int]:
    """Extract every Nth frame and return processed and saved frame counts."""

    if every_n_frames <= 0:
        raise ValueError("The frame interval must be greater than zero.")
    validate_video_path(video_path)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video file: {video_path}")

    output_directory.mkdir(parents=True, exist_ok=True)
    processed_count = 0
    saved_count = 0

    try:
        while True:
            frame_available, frame = capture.read()
            if not frame_available:
                break

            frame_number = processed_count
            if frame_number % every_n_frames == 0:
                output_path = output_directory / frame_filename(frame_number)
                if not cv2.imwrite(str(output_path), frame):
                    raise RuntimeError(f"Could not write extracted frame: {output_path}")
                saved_count += 1

            processed_count += 1
    finally:
        capture.release()

    if processed_count == 0:
        raise RuntimeError(f"No video frames could be read from: {video_path}")

    return processed_count, saved_count


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="Extract selected frames from a local video as JPEG files."
    )
    parser.add_argument("video", type=Path, help="Path to a local video file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory. Defaults to data/frames/<video-name>.",
    )
    parser.add_argument(
        "--every-n-frames",
        type=positive_integer,
        default=DEFAULT_FRAME_INTERVAL,
        metavar="N",
        help=f"Save every Nth frame (default: {DEFAULT_FRAME_INTERVAL}).",
    )
    return parser


def main() -> int:
    """Run the command-line interface."""

    args = build_parser().parse_args()
    output_directory = args.output_dir or default_output_directory(args.video)

    try:
        processed_count, saved_count = extract_frames(
            args.video, output_directory, args.every_n_frames
        )
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Frame Extraction Complete")
    print("-------------------------")
    print(f"Processed frames: {processed_count}")
    print(f"Saved images: {saved_count}")
    print(f"Output directory: {output_directory.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

