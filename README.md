# Disc Dog Analytics

**Project title:** Robust Detection and Event Recognition for Fast Small-Object Sports Analytics: A Disc Dog Case Study

**Client:** petlo.my

## Overview

This project aims to develop a computer vision-based video analytics system for pre-recorded disc dog training videos. The planned system will estimate the number of throws, successful catches, and misses; calculate a catch ratio; associate events with timestamps; and support the review of historical training performance.

The repository is currently at an early feasibility and project foundation stage. It contains planning documents, video inspection and frame extraction utilities, and a baseline object detection prototype. It is not a complete event recognition or web application.

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

The following are planned features rather than claims about the current implementation:

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
- a pretrained object detection feasibility prototype
- a dataset preparation plan
- a findings template for future experiments

The utilities are implemented, but representative-video evaluation has not yet been completed.

## Initial Technology Direction

- **Computer vision:** Python, OpenCV, PyTorch, and Ultralytics YOLO as an initial baseline candidate
- **Future backend:** FastAPI
- **Future frontend:** React and TypeScript
- **Future database:** PostgreSQL

Technology choices may change after technical evaluation. The backend, frontend, and database are not implemented in this version.

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

## Roadmap

- [x] Project definition
- [x] Initial requirements
- [x] Initial architecture
- [x] Video inspection utility
- [x] Frame extraction utility
- [x] Baseline detection prototype
- [ ] Dataset collection
- [ ] Domain-specific disc annotation
- [ ] Baseline evaluation
- [ ] Detection fine-tuning
- [ ] Object tracking
- [ ] Trajectory analysis
- [ ] Event recognition
- [ ] Backend development
- [ ] Frontend development
- [ ] Database integration
- [ ] System integration
- [ ] Testing
- [ ] Deployment

## Further Documentation

- [Project overview](docs/project-overview.md)
- [Initial requirements](docs/requirements.md)
- [Supervisor and client questions](docs/supervisor-questions.md)
- [Architecture](docs/architecture.md)
- [Dataset strategy](docs/dataset-plan.md)
- [Feasibility findings template](docs/initial-findings.md)
- [Computer vision module](cv/README.md)
