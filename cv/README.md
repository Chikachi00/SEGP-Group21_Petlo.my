# Computer Vision Feasibility Module

## Purpose

This module supports the first technical feasibility work for Disc Dog Analytics. It provides small command-line tools for video inspection, selected-frame extraction, and baseline object detection.

The code is not an event recognition system. It does not implement tracking, trajectory analysis, throw recognition, catch recognition, or miss recognition.

## Setup

From the repository root in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r cv/requirements.txt
```

Keep local videos, extracted frames, model weights, and generated output outside version control. Use only footage that the team is authorised to process.

## Available Commands

### Inspect a video

```powershell
python cv/video_info.py data/raw/sample.mp4
```

Prints the resolution, frame rate, frame count, and approximate duration.

### Extract selected frames

```powershell
python cv/extract_frames.py data/raw/sample.mp4
python cv/extract_frames.py data/raw/sample.mp4 --output-dir data/frames/sample --every-n-frames 30
```

The default interval is every 30 frames. Files use deterministic names based on their zero-based source frame number.

### Run baseline detection

```powershell
python cv/detect_video.py data/raw/sample.mp4
python cv/detect_video.py data/raw/sample.mp4 --output outputs/sample_detected.mp4
```

The script uses a lightweight pretrained Ultralytics YOLO model and retains only dog, frisbee, and person detections. COCO commonly uses `frisbee` as the flying-disc class name; this project displays that class as `disc`.

Use `--model` to select another compatible lightweight model and `--confidence` to adjust the detection threshold:

```powershell
python cv/detect_video.py data/raw/sample.mp4 --model yolo11n.pt --confidence 0.25
```

The first run may obtain model weights through the Ultralytics package. Do not add downloaded weights to the repository.

## Current Scope

- video metadata inspection
- periodic frame extraction
- pretrained object detection for dogs, discs, and people
- annotated MP4 output
- descriptive counts of frames containing relevant detections

## Current Limitations

- Small-object detection performance must be evaluated using representative project videos.
- No representative experiment has yet been recorded in `docs/initial-findings.md`.
- General pretrained models may miss a small or blurred disc.
- A person observation is not necessarily the handler.
- The output has no object identity across frames.
- Detection counts are not throw, catch, or miss counts.
- Audio is not copied to the generated video.
- The model dependency and weights must be available before detection can run.

## Expected Outputs

- `video_info.py`: a text summary of video properties
- `extract_frames.py`: selected JPEG frames and a saved-frame summary
- `detect_video.py`: an annotated MP4 and descriptive frame-level detection counts

The outputs should be reviewed and recorded honestly. If the baseline does not observe the disc, that is a useful feasibility finding rather than a result to replace or infer.

