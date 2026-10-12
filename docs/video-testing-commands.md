# Video Pipeline Testing Commands

This guide records the repeatable local workflow for testing the disc-dog sample videos. Run commands from the repository root in Windows PowerShell. The original videos are read-only; generated files belong under `outputs/` and should not be committed.

The current agreed analysis scope is the two fixed tripod views: front and side. The handheld clip is excluded from event analysis, and `setup.mp4` is an environment reference only.

## 1. Set paths

```powershell
Set-Location 'D:\Nottingham\Year 2\SEGP GROUP21'

$py = '.\.venv\Scripts\python.exe'
$sampleDir = 'D:\Nottingham\Year 2\SEGP\General\0_Data\0_SampleVideo'
$runRoot = 'outputs\manual-test-20261012'
New-Item -ItemType Directory -Force $runRoot | Out-Null
```

Use a new `$runRoot` for each experiment so earlier results remain available for comparison. If the code, detector parameters, or input video changes, do not write over the prior run.

## 2. Prepare the source video packet (only for new or changed source videos)

The existing sample packet can be reused when its manifest validates the source files. For a new directory of authorised videos, prepare a packet first:

```powershell
& $py -m cv.video_tools prepare `
  --source $sampleDir `
  --output 'outputs\video-analysis-pack'
```

This step builds timestamped browsing material locally. It does not run object detection and does not replace continuous original-frame algorithm input.

## 3. Run the per-view pipeline

Run the following block once for `front`, then again for `side`. Each stage consumes the previous stage's saved output, making it possible to inspect failures stage by stage.

```powershell
# Select the view. For the side run, change front to side and change the preview below.
$view = 'front'
$videoName = 'Landscape_Tripod_FrontView.mp4'
$previewName = 'Landscape_Tripod_FrontView.mp4'
$run = Join-Path $runRoot $view
New-Item -ItemType Directory -Force $run | Out-Null

$video = Join-Path $sampleDir $videoName
$detectionVideo = Join-Path $run 'disc-enhanced.mp4'
$detectionJsonl = Join-Path $run 'disc-enhanced.jsonl'
$dogDir = Join-Path $run 'dog-tracking'
$discDir = Join-Path $run 'disc-tracking'
$jointDir = Join-Path $run 'joint-analysis'
$eventRoot = Join-Path $runRoot 'throw-events-v3'
$eventDir = Join-Path $eventRoot "${view}-v1"
$preview = Join-Path (Get-Location) (Join-Path 'outputs\joint-previews' $previewName)

# A. Detect dog/person/disc on the original video; this also writes detection JSONL and a run summary.
& $py cv\detect_disc_video.py $video --output $detectionVideo

# B. Track the dog and disc independently from the same saved detections.
& $py cv\track_dog_video.py --detections $detectionJsonl --output-dir $dogDir
& $py cv\track_disc_recovered_video.py --detections $detectionJsonl --output-dir $discDir

# C. Combine dog and disc observations, then infer event candidates.
& $py cv\analyze_dog_disc.py `
  --dog-dir $dogDir `
  --disc-dir $discDir `
  --output-dir $jointDir `
  --preview $preview

& $py cv\analyze_throw_events_v3.py `
  --joint-dir $jointDir `
  --detections $detectionJsonl `
  --output-dir $eventDir `
  --preview $preview
```

For the side run, set:

```powershell
$view = 'side'
$videoName = 'Landscape_Tripod_SideView.mp4'
$previewName = 'Landscape_Tripod_SideView.mp4'
```

Then rerun the per-view pipeline block. Create or validate the clean joint previews before the first joint-analysis run if they are missing:

```powershell
& $py cv\prepare_joint_previews.py
```

If only tracking or event rules changed, start from that stage and rerun downstream stages. Re-run detection only when the source video, detector, or detector settings changed. Check the script's `--help` output if a future code version changes its command-line options.

## 4. Review event results and build the two-view summary

Each per-view event run writes an `index.html`, event JSON, and state JSONL under `outputs/manual-test-20261012/throw-events-v3/<view>-v1/`. Open each view's `index.html` for event-by-event review. After both fixed views finish, use the v3 review/statistics builder documented by the checked-out repository version. Its output root should be `outputs/manual-test-20261012/throw-events-v3`.

```text
outputs/manual-test-20261012/throw-events-v3/front-v1/
outputs/manual-test-20261012/throw-events-v3/side-v1/
```

Open each generated `index.html` to inspect event candidates. Review the detection video first, the independent dog/disc tracking outputs next, and the event page last. This order helps locate the stage where an error begins.

After both views have completed, fuse the two fixed-camera results. For the unchanged supplied sample only, the existing human-label file can be included because it is tied to the side-view source hash. For a new or modified video, omit `--labels` until a separate human-label file has been created and checked against that source.

```powershell
& $py cv\fuse_throw_events_v3.py `
  --root (Join-Path $runRoot 'throw-events-v3') `
  --labels 'docs\sample-event-ground-truth-20261012.json'

& $py cv\build_throw_statistics.py `
  --input (Join-Path $runRoot 'throw-events-v3\fused-results.json') `
  --output-dir (Join-Path $runRoot 'throw-events-v3\statistics-v1')
```

Open `throw-events-v3\index.html` for event evidence and `throw-events-v3\statistics-v1\statistics.html` for sample candidate statistics. The statistics builder intentionally does not use human labels to calculate rates; these are candidate rates, not measured accuracy.

## 5. Run regression tests

```powershell
& $py -m unittest discover -s tests -v
```

Record the test count and result from the actual run. Automated tests validate code behavior; they do not measure real-world detection accuracy.

## Interpretation notes

- Detection, dog tracking, disc tracking, joint analysis, and event analysis are separate stages. A later-stage error can originate in an earlier stage.
- A missing disc observation is not evidence of a miss or failed catch. Inspect the original frames around the candidate event.
- Treat `catch_candidate`, `ground_pickup_candidate`, and `uncertain` as machine-generated candidates until checked against source video and recorded as manual labels.
- Do not report candidate counts as precision, recall, or accuracy without frame/event-level ground truth.
- Front and side clips may show the same throw. Do not add their event counts as though they were independent throws.
- Tracking and image coordinates are in pixels. Real distance and speed require camera/field calibration.
