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

