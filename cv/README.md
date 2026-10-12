# Computer Vision Feasibility Module

## Purpose

This module supports the first technical feasibility work for Disc Dog Analytics. It provides small command-line tools for video inspection, selected-frame extraction, and baseline object detection.

The repository includes single-dog tracking, pixel trajectories, and a sample-bound throw-event candidate prototype with session candidate statistics. It is not a generally validated event-recognition system; mouth localization and calibrated physical measurements remain future work.

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
- single-dog IDs with separate measured/predicted positions and review-compatible JSONL

## Current Limitations

- Event outcomes and rates are unverified candidates evaluated only on the supplied fixed-angle samples.

- Small-object detection performance must be evaluated using representative project videos.
- Qualitative sample runs are documented, but there are no ground-truth accuracy measurements.
- General pretrained models may miss a small or blurred disc.
- A person observation is not necessarily the handler.
- Baseline detection outputs have no identity; the dog tracker supplies provisional IDs without appearance re-identification.
- Detection counts are not throw, catch, or miss counts.
- Audio is not copied to the generated video.
- The model dependency and weights must be available before detection can run.

## Expected Outputs

- `video_info.py`: a text summary of video properties
- `extract_frames.py`: selected JPEG frames and a saved-frame summary
- `detect_video.py`: an annotated MP4 and descriptive frame-level detection counts

The outputs should be reviewed and recorded honestly. If the baseline does not observe the disc, that is a useful feasibility finding rather than a result to replace or infer.


## Precise Video Packet and Review Workflow

The `video_tools/` package adds complete FFmpeg decoding, actual source-frame time indexes, sparse frames, per-video overview sheets, motion candidate windows, original-resolution inspection/crops, and result review. It retains the existing feasibility scripts as separate entry points.

```powershell
py -3 -m cv.video_tools prepare --source '<local-video-directory>' --output outputs/video-analysis-pack
py -3 cv/video_packet.py inspect-window --pack outputs/video-analysis-pack --video-id Portrait_Handheld --start 0 --end 1 --frame-id 0 --tiles
py -3 -m cv.video_tools review-results --pack outputs/video-analysis-pack --results outputs/tracking-v1.jsonl --processing-seconds 14.2
```

The last command requires results exported in the documented JSONL schema. The baseline `detect_video.py` does not produce that schema or track identities. The new `track_dog_video.py` consumes enhanced detection JSONL and exports review-compatible dog tracks. No detector result or recognition accuracy is implied by successful packet preparation. Setup is environment reference; the other three samples are action footage. The decoder and reader handle each source independently and record failures explicitly.

Use [the command guide](video_tools/README.md) for the complete schema and [the iteration workflow](../docs/video-analysis-workflow.md) for how to read a packet and compare algorithm runs. Local FFmpeg binaries belong in ignored `tools/ffmpeg/`; generated packets and review outputs remain in ignored `outputs/`.

## Small-disc Enhancement

`detect_disc_video.py` keeps the existing local YOLO weights and adds 1280-pixel full-frame inference plus a 2x2 grid of original-resolution crops with 20% overlap and 960-pixel tile inference. Crop inference retains the frisbee class, maps its boxes back to the full display frame, and merges duplicates. Dog/person detection uses the full frame. The default confidence stays at 0.25 for all targets; disc-only confidence is independently configurable.

```powershell
.\.venv\Scripts\python.exe cv/detect_disc_video.py '<sample-video-directory>\Landscape_Tripod_FrontView.mp4' --output outputs/front_disc_enhanced.mp4
```

This entry requires an already prepared source packet and local model weights. FFmpeg feeds continuous original-size BGR frames, verifies their real source PTS, and applies display orientation. The script produces annotated MP4, per-frame detection JSONL, and a JSON run summary beside it. There are no temporal track IDs; this detection JSONL is not directly accepted by the trajectory `review-results` command. MP4 playback uses nominal FPS, while JSONL retains real original timestamps.

Use `--start 11.5 --end 13.5` for a short continuous-frame experiment; `--mode baseline` selects full-frame 640-pixel inference with no crops. `--disc-grid 0` keeps the higher-resolution full-frame pass and disables crops for a faster run. For details and observed limitations, see [the experiment record](../docs/disc-detection-improvement.md).

## Single-dog Tracking

Run `python cv/track_dog_video.py --detections outputs/front_disc_enhanced.jsonl --output-dir outputs/dog-tracking/front-v1` from the repository root. It reuses saved detections, renders all original frames, and records true source timestamps. Green boxes are accepted measurements; dashed yellow boxes are predictions capped at 0.25 seconds. Long gaps end the old ID after 0.75 seconds.

See [implementation, results and full test commands](../docs/dog-tracking-prototype.md). The local three-video review is `outputs/dog-tracking/index.html`. Predicted positions are never exported as detected boxes to `review-results`.
