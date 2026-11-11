# Performance improvements

See [video-analysis runtime](runtime-performance.md) for the subsequent GPU,
batched inference and data-only processing changes and their runtime settings.

Measured on the local Windows development environment on 2026-10-26, against
commit `442b432`. These changes preserve the API contract and the existing
detector settings, tracking gates, event thresholds and evidence rules.

## Frontend delivery and background work

All pages now load on demand in the selected demo/API mode. Opening the video
list no longer loads the history chart library or the upload page's CSS.
The production build's main JavaScript chunk fell from **603.17 kB to
250.49 kB** (gzip **182.26 kB to 79.72 kB**). These are build artifact sizes,
not a measurement of page-load time or all resources used by every route.
The chart chunk loads when history is opened.

Removed the unused `antd` dependency and its 63 exclusively required dependency
entries from the lockfile. No dependency versions were upgraded.

History loading fetches the first page, then uses at most three concurrent page
requests while preserving the server's order. Failure or cancellation stops
outstanding requests. Hidden tabs suspend new history/status reads until visible;
server analysis continues. The existing observation deadline still applies.
The elapsed clock updates its own small component instead of rerendering the
whole analysis card every second. Stage lists and labels are reused, history
chart data is memoized, and CSV export indexes camera views once.

## Backend queries, I/O and memory

- Session listing uses three SELECTs for a nonempty page: the count, the session
  summaries with preferences/current jobs, and camera views. The original code
  could issue up to 62 SELECTs for 20 sessions. Empty pages need two SELECTs.
- Upload copying and media probing run outside the global write lock and database
  transaction. Before committing, a fresh transaction rechecks ownership, Trash,
  analysis state and duplicate camera views under the write lock. Rejected files
  are removed.
- Completed, failed and queued-cancelled jobs release their runtime futures and
  controls; saved status/results remain in the database.
- Job source copying and SHA-256 verification share one source read, using 1 MiB
  chunks and cancellation checkpoints. Hash mismatches remove the partial copy.
- Successful FFmpeg discovery is cached for one runner/server lifetime. Failed
  discovery can be retried. Restart the server after changing tool configuration.

## CV search costs

Carry searches reuse model-anchor counts/endpoints and dog-relative geometry
instead of repeatedly slicing and scanning every candidate window. Worst-case
window processing is quadratic rather than cubic. Disc association collects each
row/column's gated costs as the matrix is built, avoiding repeated matrix scans.
Duplicate filtering defers geometry until boxes overlap enough. V3 ledger updates
visit only each event's frame range; input validation already requires contiguous
source frame IDs, including ranges that start above zero.

Representative synthetic hot-loop measurements, using medians of five repeats:

| Search | Original | Optimized | Speedup |
| --- | ---: | ---: | ---: |
| Carry evidence, 180 stationary observations | 32.493 ms | 8.266 ms | 3.93x |
| Relative carry, same observations | 231.653 ms | 8.832 ms | 26.23x |
| Association, 16 tracks / 160 candidates | 16.723 ms | 1.293 ms | 12.93x |

The benchmark compares returned values with the baseline. These inputs exercise
expensive rejected windows and dense cost matrices. They do **not** establish an
equivalent improvement in YOLO inference, full-video throughput or recognition
accuracy. Timings vary by machine and load.

## Reproduce and validate

Run from the repository root in PowerShell:

```powershell
npm.cmd run build
npm.cmd run test:api
npm.cmd run lint
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts/benchmark-cv.py --baseline 442b432
```

The tests cover bounded queries, concurrent upload races, job-resource cleanup,
copy integrity/cancellation, ordered bounded history requests, hidden-tab polling,
900 exhaustive carry comparisons, 100 randomized association comparisons, and
operation-count guards for the former cubic loops.

The initial optimization pass passed 23 frontend tests, 24 backend tests and 118 CV/media
tests. The production build succeeds without the previous large-chunk warning.
Lint exits successfully with six pre-existing React hook/state warnings.

For actual model, API, persistence and HTTP range-playback validation on a local
video, use the existing isolated smoke workflow:

```powershell
.\.venv\Scripts\python.exe -m backend.smoke --video path/to/sample.mp4 --seconds 2
```

A run on an existing short smoke clip completed successfully in 20.42 seconds,
returned HTTP 206 playback and preserved the result after an API restart. It
produced no throw candidates, so it verifies integration rather than event
accuracy. The generated report is in
`outputs/backend-smoke-9d64818e1e50/smoke-report.json` (ignored by Git).

Interactive browser verification was unavailable: no in-app browser backend was
connected, and Windows browser access was denied. The production build, unit/
integration checks and actual processing smoke test provide the validation here.
