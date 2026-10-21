# Development Log: Disc-Dog Video Analysis

**Baseline date:** 12 October 2026
**Purpose:** Keep a report-friendly record of implementation status, sample evidence, and limitations. Update this file when code or evaluation results change.

## Project objective

Build an offline prototype that analyses recorded disc-dog footage. The current computer-vision pipeline detects the dog and flying disc, links observations over time, examines their joint movement, identifies throw/catch/retrieval event candidates, and presents results for review.

## Development sequence

The implementation follows an incremental, single-developer workflow: establish that each stage works and can be inspected before building on its output. The stages below describe the dependency order of the work, rather than claiming that each stage was completed once with no later revisions.

| Step | Development stage | Purpose and hand-off |
|---|---|---|
| 1 | Define scope and inspect sample footage | Confirm the initial target objects, camera views, and practical video constraints. The current event-analysis scope is the fixed front and side views; handheld footage is excluded and Setup is reference material. |
| 2 | Build reliable video reading and browsing | Decode the original clips, preserve source timestamps and orientation, and create a small local browsing pack. This makes later algorithm results traceable to original frames. |
| 3 | Establish a detection baseline | Run a pretrained detector for dog, disc, and person, and inspect its annotated output to identify the small, fast disc as a key failure source. |
| 4 | Improve disc observations | Add higher-resolution/crop inference and bounded local recovery for short detection gaps. Keep measured observations, visual recovery, and predictions distinguishable. |
| 5 | Track dog and disc independently | Link frame-level observations over time and export reviewable tracks and pixel-coordinate trajectories. This separates object detection errors from association errors. |
| 6 | Analyse dog-disc relationships | Align both tracks by source frame and time, then calculate motion, approach, and contact evidence. Treat these as candidates because whole-body boxes do not locate the dog's mouth. |
| 7 | Add event candidates and two-view fusion | Build throw, airborne-catch, ground-pickup, and uncertain outcomes from the prior evidence. Compare the front and side samples by event order, preserving uncertainty when evidence conflicts or leaves the frame. |
| 8 | Add review and candidate statistics | Generate event evidence pages and a separate summary. Keep algorithm candidate rates distinct from human-verified accuracy measures. |
| 9 | Current validation work | Finish reviewing the supplied sample events, compare candidates with those labels, fix repeatable failures, and only then expand to more videos or claim evaluation metrics. |

This order is suitable for an individual project because the stages have clear inputs and outputs, can be run and debugged independently, and limit how many causes need investigation when a result is wrong. The process remains iterative: a later review can send work back to detection, tracking, or event rules.

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

## 2026-10-20 — Frontend API preparation (local handoff)

Added a proposed v1 API contract, backend handoff checklist, public environment example, typed video/session API wrappers, shared HTTP transport, and an analysis-job polling hook. Existing page demos are intentionally not switched to a nonexistent server. The job observer cleans up requests on job change/unmount, stops on completed/failed or errors, and never automatically repeats analysis-start POST requests.

The contract preserves four candidate categories, nullable zero-denominator rates, and independent timestamps per camera. Existing sample-pair fusion remains sample-restricted; arbitrary new uploads require backend adapter work and validation. The current MySQL schema requires session/job/event persistence changes before the complete flow can be connected.

Validation: `npm run test:api` passed all 10 focused transport/polling tests; `npm run build` passed with the existing large-chunk warning. SHA-256 comparison confirmed all 59 previously tracked files under `cv/`, `src/`, `database/`, and `tests/` unchanged. This verifies preservation, not general algorithm accuracy or a working backend. No dependencies, CV algorithms, database SQL, or existing page behavior were changed. No commit, push, PR or deployment was made; the user will upload manually. The previously observed oxlint native-binding installation issue is separate.

See [API contract](api-contract.md), [backend handoff](backend-handoff.md), and [frontend preparation guide](frontend-api-preparation.md) for the exact files, response formats, local checks, and remaining integration steps.
## 2026-10-20 — Local backend/CV integration and real API pages

Implemented a loopback-only FastAPI service, additive SQLAlchemy mappings, SQLite development database and MySQL extension DDL. Routes create/read dogs and sessions, accept validated uploads, start one queued inference job per active session, query durable job state, return saved candidate events/statistics and serve source-time H.264 previews with Range support. Existing user_login/dogs/video mappings are reused; original database/petlo.sql and cv/ source files were not changed. Live MySQL connectivity remains to be tested against the teammate's actual database.

Added an isolated per-job adapter invoking the existing packet CLI, clean evidence preview, detector, dog/disc trackers, joint evidence and v3 event scripts. It reuses existing candidate statistics logic and restricts paired fusion to known source hashes without passing human labels. Original verified CFR evidence previews remain distinct from source-time browser playback. Failure/restart states are explicit; private model/video/runtime artifacts stay ignored.

Added opt-in VITE_USE_API routing to new Live pages, real upload and dog selection/creation, polling, saved list/history and per-view event playback. Original demo page files remain selectable and unchanged. Fixed Windows integration issues by shortening per-job generated names and excluding outputs/backend-data/venv/raw footage from Vite's watcher; packet execution now has its own subprocess log and timeout.

Validation: 108 existing CV regression tests, 9 backend tests, 10 client transport/polling tests, and API-mode frontend build passed. A real 0.5-second resized source clip ran through all original stages, saved null-denominator candidate statistics, supported HTTP 206 playback, and survived an API restart. Browser verification exercised actual multipart upload, a failed-job review/retry and eventual completed playback/results. Short-clip integration checks do not measure recognition accuracy; a new full paired-video run and live MySQL/public-auth deployment are not claimed. Existing large-bundle warning and optional oxlint binding issue remain separate.

The local integration has no public login/authentication service and rejects non-loopback clients. Public backend hosting/storage/credentials and multi-user authorization remain future work. No Git commit, push, PR or remote deployment was performed; user uploads manually. Start with docs/local-full-stack-testing.md and backend/README.md.

## 2026-10-21 — Local presentation flow and full original-sample verification

Hardened the existing local integration for the 2026-10-22 demonstration. Accepted uploads navigate to a dedicated saved-task route; reloads and navigation restore current_job_id without re-uploading or starting another analysis. The page displays actual pipeline stages, persisted submission/completion elapsed time and the last successful status query. Connection errors offer observation-only reconnection; no percentage, ETA or worker heartbeat is invented. The saved list refreshes active sessions without replacing the original demo mode.

Added backend-configured upload-size preflight (local default remains 1024 MiB for the original 271 MiB side sample), backend readiness checks, candidate-statistics cards, per-camera event playback and downloadable report JSON/event CSV. CSV has one event/view per row, preserves independent view times and marks outcomes unverified; exports do not alter inference. Added checked loopback-only startup/idle-stop scripts, service logs and a presentation rehearsal/failure checklist. Original cv/ sources, original petlo.sql and original four demo page files were unchanged by SHA-256 comparison (39 protected files checked). No dependency upgrades, Git commit, push or deployment were performed.

Validation: 108 existing CV tests, 10 backend tests, 13 frontend tests, API-mode build and original-demo-mode build passed. Browser checks exercised an actual short-file upload, automatic queued-task navigation, reload of the same task, active-list/failed-restart views, and a narrow viewport with no horizontal overflow or console errors. The full unmodified 1080p front and 4K HEVC side samples were uploaded via the running API, processed sequentially through the original stages and fused, completing in approximately 41.1 minutes on the installed CPU-only PyTorch environment. This includes upload/preparation/rendering and is one observed run, not a performance guarantee. Actual statistics: {"in_air_catch_candidate": 3, "ground_pickup_candidate": 1, "miss_candidate": 0, "uncertain": 0}; uncertain events: 0. Human labels were not supplied to inference. The browser short-clip check validates plumbing only.

Both completed sessions, task identities, timestamps, statistics and HTTP 206 video playback survived a real backend restart. Local audit: outputs/local-demo-validation-20261021.json; full-run record: outputs/demo-check-18b29962f4/report.json. The full report remains in the configured local database for honest precomputed-result demonstration while a new task runs. See docs/local-demo-checklist.md. MySQL connectivity, public authentication/deployment and independent algorithm accuracy remain outside this local verification. The pre-existing large-bundle warning remains.

Final browser QA confirmed JSON download with four candidates, CSV with eight event/view rows, source-time seeking at 10.633s (front) and 10.978s (side), and no horizontal overflow. Checked startup, safe idle stop and repeated stop behavior; left the local backend available for rehearsal.

## 2026-10-21 — Readable session names and real task controls

After the local upload/report flow was working, improved session management for rehearsal: show editable display labels instead of UUID fragments, accept an optional name during upload, and retain internal IDs in collapsed technical details. Added recoverable Trash/Restore rather than physical source deletion. Deleting active work requests cancellation; restoring saved data never silently restarts inference.

Added an isolated process-control wrapper around existing pipeline subprocess calls. Pause suspends the owned CV/FFmpeg process tree; Resume continues the same job/process; Stop cancels it and preserves uploaded videos for a new attempt. UI observes acknowledged pausing/paused/cancelling/cancelled states, avoids duplicate control requests, and continues observing paused tasks. Paused time does not consume the stage timeout, although wall-clock elapsed includes it. The backend must remain running; persistent checkpoint recovery and multiple workers remain outside scope. No original CV algorithms or original petlo.sql were edited.

Persistence uses one additive analysis_session_preferences table, without rewriting old sessions. Existing full paired report remained four candidates (three airborne, one pickup), and the user's front-only run completed before the service was restarted. Supplied an additive MySQL SQL file but did not claim live MySQL testing. Added pinned psutil, already installed locally; no dependency upgrade was performed.

Validation: all 16 backend tests and 15 frontend tests passed; API-mode TypeScript/Vite production build passed with the existing bundle-size warning. Backend tests verify name/ownership constraints, restore of original reports/media across restart, duplicate-analysis protection while paused, cancellation and actual parent/child process suspension with pause-aware timeout accounting. Browser checks verified Rename, Trash/Restore and actual Pause/Resume on a short real-CV task. These tests validate application behavior, not recognition accuracy. Local audit: outputs/session-control-smoke-20261021.json. No Git commit, push or remote deployment was performed.
