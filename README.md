# Disc Dog Analytics

[中文](README.zh-CN.md) | [English](README.md)

[Live Demo](https://petlo-tracking.pages.dev/) · [Development Log](docs/development-log.md)

> The online demo currently shows the interface prototype and sample data. Use the local version below for real video analysis and completed reports.

**Project title:** Robust Detection and Event Recognition for Fast Small-Object Sports Analytics: A Disc Dog Case Study

**Client:** petlo.my

## Overview

This project aims to develop a computer vision-based video analytics system for pre-recorded disc dog training videos. The planned system will estimate the number of throws, successful catches, and misses; calculate a catch ratio; associate events with timestamps; and support the review of historical training performance.

The project has progressed from feasibility work to a sample-bound algorithm prototype. The repository contains video inspection, enhanced object detection, dog and disc tracking, joint analysis, throw-event candidates, two-angle sample fusion, and candidate session statistics. A local web/API integration is implemented; general event-recognition accuracy, production multi-user access and a public algorithm backend remain unverified or pending.

## Problem

Manually reviewing training footage is time-consuming. Automated analysis could make it easier to summarise a session, but the footage presents difficult computer vision conditions:

- small flying discs
- high-speed motion and motion blur
- temporary disappearance and occlusion
- complex backgrounds
- different camera distances
- varying recording environments

These challenges have not yet been resolved. Representative project videos and labelled evidence are needed before detection quality or event recognition can be evaluated.

## Planned Pipeline

```mermaid
flowchart LR
    A[Video] --> B[Object Detection]
    B --> C[Object Tracking]
    C --> D[Trajectory Analysis]
    D --> E[Event Recognition]
    E --> F[Statistics]
    F --> G[Web Application]
```

Detection, tracking, and event recognition are separate stages. A detected or temporarily disappearing disc does not by itself prove that a throw, catch, or miss occurred.

## Planned Core Features

The following are product goals; the local implementation and its limits are described below:

- video upload
- dog detection
- disc detection and tracking
- throw, catch, and miss detection
- catch ratio calculation
- event timeline
- session history
- historical analytics

## Current Development Stage

The current repository provides:

- initial project requirements
- an initial current and future architecture
- video inspection utilities
- deterministic frame extraction
- real-timestamp video packets, motion candidates, crop inspection, and result-review tooling
- pretrained object detection with a small-disc enhancement tested on four samples
- single-dog IDs, bounded gap prediction, pixel trajectories and tracking replays
- a dataset preparation plan
- a findings template for future experiments

Four local sample videos have passed complete decoding and packet preparation, including 4K HEVC. The event candidate prototype analyzes the fixed front and side samples, and a separate session-statistics report summarizes candidate outcomes without using human labels. The user-reviewed side-view labels are three in-air catches and one ground pickup; v3 combines the matching ordered views to produce the same four candidate outcomes. These four attempts were used during rule development, so the 4/4 sample match is not an independent accuracy estimate. The side-only second event remains uncertain because the disc leaves frame; the front view supplies a ground-pickup candidate.

## Initial Technology Direction

- **Computer vision:** Python, OpenCV, PyTorch, and Ultralytics YOLO as an initial baseline candidate
- **Backend (local):** FastAPI with a background CV job adapter
- **Frontend:** React, TypeScript and Vite, with separate demo/API modes
- **Database:** SQLite for local integration tests; SQLAlchemy mappings and additive DDL for the teammate's MySQL schema

Technology choices may change after technical evaluation. A Vite/React frontend and a local FastAPI backend integration are now implemented. SQLite is used for local tests, with additive mappings for the teammate's MySQL schema. Production authentication and a public backend deployment remain pending.

## Local Web Demonstration (2026-10-22)

After installing the dependencies in [local full-stack testing](docs/local-full-stack-testing.md), run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-local-demo.ps1 -OpenBrowser
```

This starts or reuses loopback-only services without uploading code or modifying the CV algorithms. Uploads open a recoverable task-status page with real stage names and submission elapsed time. Completed sessions provide per-view event playback, candidate statistics, JSON/CSV downloads and saved history. There is no fabricated processing percentage or ETA. Keep the backend running while jobs execute.

Use the [presentation checklist](docs/local-demo-checklist.md) to rehearse with complete original samples, preserve saved reports and handle connection errors. Local uploads default to 1024 MiB per file to accommodate the unmodified side sample; this is separate from public hosting limits.

## Quick Start

The commands below assume Windows PowerShell and are run from the repository root.

1. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install the current computer vision dependencies:

   ```powershell
   python -m pip install -r cv/requirements.txt
   ```

3. Place a locally authorised test video in `data/raw/`. Video files in this directory are ignored by Git.

4. Inspect its metadata:

   ```powershell
   python cv/video_info.py data/raw/sample.mp4
   ```

5. Extract every thirtieth frame, or choose another positive interval:

   ```powershell
   python cv/extract_frames.py data/raw/sample.mp4
   python cv/extract_frames.py data/raw/sample.mp4 --output-dir data/frames/sample --every-n-frames 30
   ```

6. Run the pretrained detection baseline:

   ```powershell
   python cv/detect_video.py data/raw/sample.mp4
   python cv/detect_video.py data/raw/sample.mp4 --output outputs/sample_detected.mp4
   ```

The first detector run may obtain the lightweight model weights through the Ultralytics package. Model weights and generated videos must remain outside version control.

## Precise Video Packets and Algorithm Review

The packet workflow uses FFmpeg and ffprobe to retain every real source-frame timestamp. It creates sparse browsing frames, four overview sheets, motion-based candidate windows, and reversible original-pixel crops. It can also review the dog tracker's JSONL output with annotated stills, continuous-frame HTML playback, and comparable-run diagnostics.

From the repository root, use a local FFmpeg/ffprobe pair in `tools/ffmpeg/` or supply `--ffmpeg-dir`:

```powershell
py -3 -m cv.video_tools prepare --source '<sample-video-directory>' --output outputs/video-analysis-pack
py -3 -m cv.video_tools inspect-window --pack outputs/video-analysis-pack --video-id Portrait_Handheld --start 0 --end 1 --frame-id 0 --tiles
```

The existing packet is available locally at `outputs/video-analysis-pack/index.html`. Its first model-reading step uses four overview sheets; a detailed batch contains at most eight independent images. Preprocessing runs offline without GPT calls. Image reading and coding still consume model usage.

See [the video workflow](docs/video-analysis-workflow.md) and [the detailed command guide](cv/video_tools/README.md). `track_dog_video.py` converts saved enhanced detections into the validated track-result format. See [dog tracking and test commands](docs/dog-tracking-prototype.md); the existing baseline `detect_video.py` remains a separate entry.

## Roadmap

- [x] Project definition
- [x] Initial requirements
- [x] Initial architecture
- [x] Video inspection utility
- [x] Frame extraction utility
- [x] Real-timestamp video packet and review tools
- [x] Complete decoding of four local sample videos
- [x] Baseline detection prototype
- [ ] Dataset collection
- [ ] Domain-specific disc annotation
- [ ] Baseline evaluation
- [ ] Detection fine-tuning
- [x] Single-dog tracking prototype and pixel trajectory export
- [ ] Disc tracking and identity evaluation
- [ ] Calibrated trajectory analysis
- [x] Throw-event candidate prototype
- [x] Sample throw-event statistics prototype
- [ ] General event recognition evaluation
- [x] Local backend API and CV job integration
- [ ] Public backend authentication and hosting
- [x] Frontend demo and opt-in API pages
- [x] Local SQLite persistence
- [ ] Live MySQL connection validation
- [x] Local video-to-result integration
- [ ] Production system integration
- [ ] Testing
- [x] Static frontend deployment
- [ ] Public backend deployment

## Further Documentation

- [Project overview](docs/project-overview.md)
- [Initial requirements](docs/requirements.md)
- [Supervisor and client questions](docs/supervisor-questions.md)
- [Architecture](docs/architecture.md)
- [Dataset strategy](docs/dataset-plan.md)
- [Feasibility findings template](docs/initial-findings.md)
- [Computer vision module](cv/README.md)
- [Video analysis workflow](docs/video-analysis-workflow.md)
- [Dog tracking implementation and sample tests](docs/dog-tracking-prototype.md)
- [Throw-event v3 sample evaluation](docs/throw-events-v3.md)
- [Draft user requirements specification](docs/user-requirements-specification.md)
- [Throw-event sample statistics](docs/throw-events-v3.md#样本事件统计)


## Local full-stack integration (2026-10-20)

The unchanged CV stages are now wrapped by a loopback-only FastAPI service with persisted video/session/job/event records and real source-time playback. Set `VITE_USE_API=true` for the network-backed pages; omit the flag or set it false for the original demo. See [the local full-stack testing guide](docs/local-full-stack-testing.md), [backend startup and limitations](backend/README.md), and [the API contract](docs/api-contract.md). Do not publish private environment files, databases, uploads, model weights or generated artifacts. The existing Pages site remains a frontend deployment; it does not run this local Python service.
