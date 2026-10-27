# Video-analysis runtime

On 2026-10-27, the same 2-second, 60-frame test input completed in **109.38 s
before this runtime pass and 38.97 s afterward**: **64.37% less wall time**, or
2.81x faster on this local machine. The comparison includes job startup and
model loading, not HTTP upload or database work. See the measurement details
below; this is a short integration fixture, not a general throughput estimate.

The API runs a job inside one isolated worker process. Detection and disc recovery
reuse the same loaded YOLO model, including across the two supported sample views.
Pause, resume, cancellation and per-stage active-time deadlines still apply to
that process and its FFmpeg children.

API jobs retain all source frames, true timestamps, detection/tracking evidence,
identity colour features, event data and statistics. They skip offline review
videos, JPEG contact sheets, contact galleries and HTML that the web application
does not consume. Standalone CV commands still generate their full review output
by default; their `--no-review` options opt into data-only processing.

Further runtime changes:

- Equal-sized disc crops are processed in batches of four with the same
  rectangular padding, crop coordinates, thresholds and resolutions. Standalone
  detection defaults to one crop at a time.
- Read-only detection/recovery avoid copying the entire decoded BGR frame again.
  Writable frames remain the default for callers that annotate video.
- Repeated FFmpeg version subprocesses are cached while both executable files are
  unchanged. Changed binaries and failed probes trigger fresh checks.
- Browser previews prefer NVIDIA H.264 encoding and fall back to software H.264
  when hardware encoding fails. Both preserve frame timestamps without an output
  frame-rate override. The CPU fallback disables B-frame reordering to preserve
  complete MP4 duration on sparse variable-frame-rate inputs.

## Local GPU setup

The local `.venv` now uses `torch==2.14.1+cu130` and
`torchvision==0.29.1+cu130`, replacing the CPU builds of the same base versions.
The downloaded wheels were checked against SHA-256 hashes from the official
PyTorch CUDA 13.0 index. The existing NVIDIA driver is used; no driver replacement
is needed for this environment. CUDA tensor multiplication and torchvision CUDA
NMS have been exercised on the RTX 4050 Laptop GPU.

PyTorch installation guidance is available from
[the official local installation guide](https://docs.pytorch.org/get-started/locally/).
The exact packages used here can be installed into an already prepared environment
with:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip install torch==2.14.1+cu130 torchvision==0.29.1+cu130 --index-url https://download.pytorch.org/whl/cu130
```

Other machines should choose a PyTorch build compatible with their Python version,
GPU and driver. GPU and batched floating-point computations can differ slightly
from sequential CPU computations; these changes do not establish recognition
accuracy.

## Settings and measurement

Defaults, also shown in `backend/.env.example`:

```dotenv
PETLO_DEVICE=auto
PETLO_CPU_THREADS=8
PETLO_TILE_BATCH_SIZE=4
```

`auto` selects CUDA when available and otherwise CPU. Use `cpu` or a CUDA device
index such as `0` to select explicitly. An unavailable explicitly requested CUDA
device causes a job failure. Restart the backend after changing these settings.
Each job records `runtime.json`, `timings.json` and `preview-encoders.json` in its
isolated storage directory.

Measure an actual video without modifying saved sessions:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark-analysis.py --video path/to/sample.mp4 --device auto
.\.venv\Scripts\python.exe scripts/benchmark-analysis.py --video path/to/sample.mp4 --device cpu --tile-batch-size 1
```

The script records real wall time and stage durations in a new ignored
`outputs/runtime-benchmark-*` directory. Benchmark model workloads sequentially;
power state, other workloads and cold imports affect results. For API upload,
playback and persistence validation, use `python -m backend.smoke --video ...`.

## Measured results and limits

The full-pipeline comparison used an i7-13650HX, RTX 4050 Laptop GPU with 6 GB
VRAM, PyTorch 2.14.1+cu130 and the existing YOLO11n weights. The input is a
640x1138 H.264 smoke clip repeated four times to make 2 seconds / 60 frames.
The saved source tree from the start of this runtime pass runs the original
CPU-only, sequential subprocess pipeline with full review artifacts. The updated
pipeline uses CUDA, four-crop batches, one model per job and data-only stages.
NVIDIA H.264 encoding was selected for browser playback.

| Run | Wall time | Frames processed |
| --- | ---: | ---: |
| Original CPU pipeline | 109.376 s | 60 |
| Updated GPU pipeline | 38.970 s | 60 |

These runs were sequential, on the same input and installed package versions.
Both preserved every frame ID and source timestamp, produced the same detection
labels/origins per frame and the same session statistics. CPU/GPU bounding boxes
differed by at most 0.577 pixels and confidence by at most 0.00115. The fixture
produced no throw candidates, so this verifies integration, not event accuracy.
Cold imports and CUDA initialization remain significant for short clips.

Reports, ignored by Git:

- `outputs/runtime-benchmark-cpu-before-2s/report.json`
- `outputs/runtime-benchmark-gpu-2s/report.json`

A separate warmed GPU comparison on source frames 0, 30 and 59, with three
alternating repeats, measured median detection time of **393.62 ms/frame with
individual crops vs 227.48 ms/frame with four-crop batches** (1.73x). The returned
detections were identical in that comparison. It covers only three source frames.
Reproduce with:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark-detector.py --video path/to/sample.mp4 --device 0 --repeats 3
```

Final checks passed: **45 backend tests, 138 CV/media tests and 23 frontend
tests**, production build, and `pip check`. Lint retains six pre-existing React
warnings. A real GPU API smoke run completed with HTTP 206 playback and saved
results surviving restart; its report is
`outputs/backend-smoke-d18b50ef4ead/smoke-report.json`. Tests also cover real
parent/child pause/cancel behavior, progress-driven stage deadlines, paired model
reuse, CPU encoding fallback and exact variable-frame-rate playback timestamps.
