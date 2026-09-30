"""Run a pretrained object detection baseline on a local video."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any

import cv2


DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.25
RELEVANT_CLASSES = {"dog", "frisbee", "person"}
DISPLAY_LABELS = {"frisbee": "disc"}
BOX_COLOURS = {
    "dog": (46, 204, 113),
    "frisbee": (52, 152, 219),
    "person": (241, 196, 15),
}


def probability(value: str) -> float:
    """Convert a command-line value to a probability between zero and one."""

    try:
        parsed_value = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Confidence must be a number.") from error
    if not 0.0 <= parsed_value <= 1.0:
        raise argparse.ArgumentTypeError("Confidence must be between 0 and 1.")
    return parsed_value


def default_output_path(video_path: Path) -> Path:
    """Return the default annotated-video path for an input video."""

    return Path("outputs") / f"{video_path.stem}_detected.mp4"


def display_label(class_name: str) -> str:
    """Return the project-facing label for a detector class name."""

    return DISPLAY_LABELS.get(class_name, class_name)


def validate_paths(video_path: Path, output_path: Path) -> None:
    """Validate input and output paths before processing begins."""

    if not video_path.exists():
        raise ValueError(f"Video file does not exist: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Video path is not a file: {video_path}")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("The output path must use the .mp4 file extension.")
    if video_path.resolve() == output_path.resolve():
        raise ValueError("The output path must be different from the input path.")


def load_detection_model(model_name: str) -> Any:
    """Load an Ultralytics detection model with a helpful dependency error."""

    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError(
            "Ultralytics is not installed. Run: "
            "python -m pip install -r cv/requirements.txt"
        ) from error

    try:
        return YOLO(model_name)
    except Exception as error:
        raise RuntimeError(f"Could not load detection model '{model_name}': {error}") from error


def model_class_names(model: Any) -> dict[int, str]:
    """Return a consistent class-ID mapping from an Ultralytics model."""

    names = model.names
    if isinstance(names, dict):
        return {int(class_id): str(name) for class_id, name in names.items()}
    return {class_id: str(name) for class_id, name in enumerate(names)}


def relevant_detections(
    result: Any, class_names: dict[int, str]
) -> list[tuple[int, int, int, int, float, str]]:
    """Convert relevant result boxes to simple values used by the display layer."""

    detections: list[tuple[int, int, int, int, float, str]] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return detections

    for box in boxes:
        class_id = int(box.cls[0].item())
        class_name = class_names.get(class_id, "unknown").lower()
        if class_name not in RELEVANT_CLASSES:
            continue

        confidence = float(box.conf[0].item())
        x_min, y_min, x_max, y_max = (
            int(value) for value in box.xyxy[0].tolist()
        )
        detections.append(
            (x_min, y_min, x_max, y_max, confidence, class_name)
        )

    return detections


def draw_detection(
    frame: Any, detection: tuple[int, int, int, int, float, str]
) -> None:
    """Draw one bounding box and confidence label on a frame."""

    x_min, y_min, x_max, y_max, confidence, class_name = detection
    colour = BOX_COLOURS[class_name]
    label = f"{display_label(class_name)} {confidence:.2f}"

    cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), colour, 2)
    label_size, baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
    )
    label_top = max(y_min, label_size[1] + baseline + 4)
    cv2.rectangle(
        frame,
        (x_min, label_top - label_size[1] - baseline - 4),
        (x_min + label_size[0] + 6, label_top),
        colour,
        -1,
    )
    cv2.putText(
        frame,
        label,
        (x_min + 3, label_top - baseline - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )


def run_detection(
    video_path: Path,
    output_path: Path,
    model_name: str,
    confidence: float,
) -> tuple[dict[str, int], float]:
    """Process a video and return frame-level detection counts and elapsed time."""

    validate_paths(video_path, output_path)
    model = load_detection_model(model_name)
    class_names = model_class_names(model)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video file: {video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Could not determine the input video resolution.")
    if fps <= 0:
        capture.release()
        raise RuntimeError("Could not determine a positive input video FPS.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    codec = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), codec, fps, (width, height))
    if not writer.isOpened():
        capture.release()
        writer.release()
        raise RuntimeError(f"Could not create output video: {output_path}")

    counts = {
        "processed_frames": 0,
        "dog_frames": 0,
        "disc_frames": 0,
        "person_frames": 0,
    }
    started_at = time.perf_counter()

    try:
        while True:
            frame_available, frame = capture.read()
            if not frame_available:
                break

            prediction = model.predict(
                source=frame, conf=confidence, verbose=False
            )[0]
            detections = relevant_detections(prediction, class_names)
            classes_in_frame = {item[5] for item in detections}

            for detection in detections:
                draw_detection(frame, detection)

            counts["processed_frames"] += 1
            if "dog" in classes_in_frame:
                counts["dog_frames"] += 1
            if "frisbee" in classes_in_frame:
                counts["disc_frames"] += 1
            if "person" in classes_in_frame:
                counts["person_frames"] += 1

            writer.write(frame)
    finally:
        capture.release()
        writer.release()

    elapsed_seconds = time.perf_counter() - started_at
    if counts["processed_frames"] == 0:
        raise RuntimeError(f"No video frames could be read from: {video_path}")

    return counts, elapsed_seconds


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Create an annotated MP4 using a pretrained dog, disc, and person "
            "detection baseline."
        )
    )
    parser.add_argument("video", type=Path, help="Path to a local video file.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Annotated MP4 path. Defaults to outputs/<video-name>_detected.mp4.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ultralytics model name or local weight path (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--confidence",
        type=probability,
        default=DEFAULT_CONFIDENCE,
        help=f"Detection confidence threshold (default: {DEFAULT_CONFIDENCE}).",
    )
    return parser


def main() -> int:
    """Run the command-line interface."""

    args = build_parser().parse_args()
    output_path = args.output or default_output_path(args.video)

    try:
        counts, elapsed_seconds = run_detection(
            args.video,
            output_path,
            args.model,
            args.confidence,
        )
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Detection Observations")
    print("----------------------")
    print(f"Processed frames: {counts['processed_frames']}")
    print(f"Frames containing dog detections: {counts['dog_frames']}")
    print(f"Frames containing disc detections: {counts['disc_frames']}")
    print(f"Frames containing person detections: {counts['person_frames']}")
    print(f"Elapsed processing time: {elapsed_seconds:.2f} seconds")
    print(f"Output video: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

