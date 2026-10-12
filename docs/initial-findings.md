# Initial Computer Vision Feasibility Findings

## Experiment Status

Not yet completed.

Results should be added after running the baseline detector on representative project videos.

The current repository contains an experiment tool and this reporting template, but it contains no representative-video result or ground-truth evaluation.

## Test Videos

| Video | Resolution | FPS | Duration | Environment | Notes |
|---|---:|---:|---:|---|---|

Do not add private filenames or identifying details to a public version of this table. A stable local reference or approved identifier may be used instead.

## Experiment Configuration

Record the following before interpreting observations:

| Field | Value |
|---|---|
| Date | Not yet recorded |
| Code revision | Not yet recorded |
| Model and version | Not yet recorded |
| Confidence threshold | Not yet recorded |
| Hardware | Not yet recorded |
| Input video reference | Not yet recorded |
| Output video reference | Not yet recorded |

## Baseline Detection Observations

### Dog Detection

Not yet evaluated.

### Disc / Frisbee Detection

Not yet evaluated.

### Handler Detection

Not yet evaluated.

The detector's frame counts are observations only. They are not evaluation metrics and do not indicate whether throws or catches were recognised.

## Failure Cases to Observe

- small disc
- motion blur
- occlusion
- background confusion
- disc outside the frame
- camera motion

## Next Steps

1. Run the baseline detector on authorised, representative videos.
2. Record the experiment configuration and qualitative observations.
3. Create a small labelled evaluation sample.
4. Evaluate small-disc detection quality with agreed metrics.
5. Decide whether domain-specific fine-tuning is necessary.
6. Expand the annotated dataset only if the evidence supports that step.


## Completed Source-Reading Validation

This is a video decoding and tool validation result, not a pretrained detector experiment. Detector observations above remain unevaluated.

| Local sample ID | Codec | Display size | Complete source frames | Motion windows |
|---|---|---|---:|---:|
| Landscape_Tripod_FrontView | H.264 | 1920 x 1080 | 2200 | 2 |
| Landscape_Tripod_SideView | HEVC (hvc1) | 3840 x 2160 | 2163 | 2 |
| Portrait_Handheld | H.264 | 2160 x 3840 | 179 | 2 |
| Setup | H.264 | 1920 x 1080 | 1198 | 0 |

All 5,740 source frames were decoded and indexed by actual PTS. Four overview sheets cover 20 selected real frames. The packet has source hashes, reversible image-coordinate mappings, and per-video caches. Four first/middle/last overview sequences and portrait orientation were visually checked. Fourteen media/contract tests passed, covering VFR, rotation, static frames, HEVC, crops, cache repair, and result validation.

Portable build: FFmpeg/ffprobe `n8.1.3-17-gc389840894-20261010`, obtained from the official-download-page-linked BtbN distribution with TLS verification and a checked SHA256. Local details are in ignored `tools/ffmpeg/download-record.json`; the packet records exact source signatures in its manifest.

Source files remained unchanged. The packet's `ACCEPTANCE.md` records the local validation evidence. No recognition accuracy, throw/catch count, or physical speed was measured. The current detector has not been run as part of this packet integration.
