# Development Log: Disc-Dog Video Analysis

**Baseline date:** 12 October 2026
**Purpose:** Keep a report-friendly record of implementation status, sample evidence, and limitations. Update this file when code or evaluation results change.

## Project objective

Build an offline prototype that analyses recorded disc-dog footage. The current computer-vision pipeline detects the dog and flying disc, links observations over time, examines their joint movement, identifies throw/catch/retrieval event candidates, and presents results for review.

## Development history and current status

| Area | Status at this baseline | Evidence and limits |
|---|---|---|
| Video reading | Implemented | The four supplied clips were decoded and indexed locally, including the HEVC side-view clip. The original source videos remain unchanged. |
| Video browsing pack | Implemented | Timestamped frame indexes, overview sheets, candidate windows, and on-demand crops support local inspection. Sparse browsing frames are not used as algorithm input. |
| Object detection | Implemented as a sample-tested prototype | YOLO detects person, dog, and disc. A higher-resolution/tiled disc-detection path improves small-disc observations, but occasional missed detections remain. |
| Dog tracking | Implemented as a prototype | Per-frame detections are linked into dog tracks, with short bounded predictions across gaps and reviewable outputs. Predictions are kept distinct from observed detections. |
| Disc tracking | Implemented as a prototype | Disc observations are associated over frames and exported as track/trajectory data. Occlusion, off-screen periods, and long gaps can break or confuse tracks. |
| Dog-disc joint analysis | Implemented | Time-aligned observations support motion, distance, approach, and contact candidates. Geometry involving the whole dog box does not establish mouth contact. |
| Event analysis | Implemented as a rule-based candidate system | v3 adds reviewable airborne-catch and ground-pickup evidence while retaining `uncertain` when observations are insufficient. It does not claim certainty from a disc disappearing. |
| Front/side result fusion and session summary | Implemented as a sample prototype | Fixed front and side views are paired by event order for this known sample and summarized in a review page and a separate candidate-statistics page. The same throw may appear in both cameras, so these are not independent counts. |
| Human verification | Side sample reviewed; front sample partly reviewed | Side throws 1, 3, and 4 were manually confirmed as airborne catches; throw 2 landed and was picked up by the dog. The disc left the frame during part of throw 2. The current front/side fusion matches these four side labels by event order, but this is same-sample development evidence, not an independent accuracy estimate. |
| Accuracy evaluation | Not yet established | There is no sufficiently large, independently annotated test set. Candidate counts and automated test success are not precision, recall, or accuracy. |
| Calibrated physical measurements | Not implemented | Current trajectory coordinates are pixels. Distance and speed in physical units require camera/field calibration. |
| Product application | Not implemented | The current deliverable is an offline analysis prototype and review workflow, not a complete web application or deployed service. |

## Current testing approach

Use the front and side fixed-tripod samples as the current analysis scope. Keep the handheld clip and Setup clip outside event evaluation. Run enhanced detection, dog tracking, recovered-disc tracking, joint analysis, v3 event analysis, two-view fusion, and candidate statistics as distinct stages. Preserve every experiment under a new `outputs/` directory. The reproducible PowerShell procedure is in [`video-testing-commands.md`](video-testing-commands.md).

For each run, review the stages in order: enhanced detections, dog tracks, disc tracks, joint analysis, then event candidates. Compare the output with the original video and record confirmed human labels separately from model predictions. Re-run the same source and time range after an algorithm change so the comparison remains meaningful.

## Known sample findings

- The front sample contains multiple throws, with occasional disc-detection/track gaps.
- The side sample contains four manually reviewed episodes: three airborne catches and one ground pickup. The ground-pickup episode includes an interval where the disc is outside the image, which limits what a single-view algorithm can infer.
- A ground pickup should be reported separately from an airborne catch. It may count as retrieving the disc, depending on the product definition, but it is not an airborne catch.
- If the disc or dog is outside the camera view, an event can remain uncertain even when a human who watched the full scene knows what happened.
- The current sample statistics report 3 airborne-catch candidates and 1 ground-pickup candidate among 4 classified events (75% airborne-catch candidate rate, 100% retrieval candidate rate, and 100% candidate coverage). These figures are generated candidate statistics; human labels are not used in their calculation, and they are not accuracy metrics.
- The v3 regression suite was reported as 108 passing tests at this baseline. Re-run the suite and record its actual result when preparing a new report or submitting a code change.

## Reporting guidance

Describe the current system as a prototype that runs detection, tracking, joint-motion analysis, event-candidate generation, two-view sample fusion, and review on the supplied samples. Report observed frame/event counts as run outputs only. Report manual labels and system candidates side by side, and calculate evaluation metrics only after defining a ground-truth annotation protocol and checking a representative set independently.

For future evaluation, annotate the event type and relevant time interval, including `airborne_catch`, `ground_pickup`, `miss`, and `uncertain/out_of_view`. Keep front and side views of the same throw in the same train/validation/test group. Record software/model versions, thresholds, source-video identity, processing time, and any manual corrections for each run.

## Next development and evaluation steps

1. Complete manual review of the front and side sample episodes and save the labels with source timestamps.
2. Compare event candidates with those labels; list false candidates, missed events, duplicate events, and uncertain/out-of-view cases.
3. Fix the highest-impact repeatable failure, then rerun the same clips with a new output version.
4. Expand the sample set only after this baseline pipeline has been checked end to end on the current clips.
5. Define how the product should count ground pickups before publishing a retrieval or catch rate.
