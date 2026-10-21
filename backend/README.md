# Petlo local backend integration

This is a working loopback-only, single-user development service wrapping the unchanged `cv/` prototype. It implements the v1 session/video/job/results flow, SQLite persistence, an additive MySQL schema mapping, fixed-camera analysis and source-time video playback. Public authentication, production scheduling/storage and independent recognition accuracy evaluation remain separate work.

## Start locally (two terminals)

Run commands from the repository root. Existing CV dependencies, a local YOLO weight file and a portable FFmpeg/ffprobe pair are required for real analysis.

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m pip install -r cv\requirements.txt -r backend\requirements-dev.txt
Copy-Item backend\.env.example backend\.env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --env-file backend/.env
```

Do not overwrite an existing local environment file; copy the example only for first setup. Open `http://127.0.0.1:8000/docs` for generated OpenAPI documentation. The default database creates a clearly labelled local development user and dog; add real test dogs through the upload page or `POST /api/v1/dogs`. There is no login endpoint in this local mode. The configured `PETLO_LOCAL_USER_ID` is server-owned.

Terminal 2:

```powershell
Copy-Item .env.example .env.local
npm ci
npm run dev
```

The frontend example sets `VITE_USE_API=true` and `VITE_API_BASE_URL=http://localhost:8000/api/v1`. Visit `http://localhost:5173`. Both `localhost` and `127.0.0.1` frontend origins are allowed by default. Restart Vite after changing environment settings. `VITE_USE_API=false` (or absent) preserves the original demo pages. API mode never falls back to sample data after a request failure.

## Files and persistence

- `config.py`: private server environment configuration.
- `db.py`: mappings for the existing `user_login`, `dogs`, `video` tables plus four result/job `analysis_*` tables and the additive `analysis_session_preferences` table. It does not change `database/petlo.sql` or use compulsory uncalibrated distance/height values.
- `main.py`, `schemas.py`: local HTTP routes, ownership checks, request schemas, multipart upload limits, structured errors, CORS, and Range-capable MP4 playback.
- `jobs.py`: a single background inference executor, durable job records, atomic result saving and explicit interrupted-job failures on restart.
- `pipeline.py`: isolated per-job inputs, safe subprocess argument lists, original CV commands, original verified evidence previews and a separate source-time H.264 browser preview.
- `smoke.py`: actual API/database/CV/media verification on an isolated input; `db_init.py` initializes or prints schema.

Default runtime paths are ignored by Git: `backend/data/petlo.sqlite3`, `outputs/backend-storage/`, `backend/.env`, `.env.local`. Each job keeps copied input, FFmpeg packet, detector/tracker/event outputs, provenance and a `pipeline.log`. Original videos are only read. Repeated analysis produces a new job/output folder and never overwrites earlier analysis artifacts. Per-view metadata uses real fractional duration and orientation-normalized dimensions.

`create_all` only creates missing tables; it does not migrate existing incompatible schemas. Run one API process with one worker. Do not use `--workers 2` or automatic reload while jobs run. A graceful shutdown requests cancellation of active tasks, including paused tasks, then waits for owned processes to exit. The checked stop script refuses to stop active work. A forced/interrupted service marks remaining active jobs failed on next startup rather than inventing completion. This is a local executor, not a production distributed queue. Free disk capacity must cover uploads, job copies, frames and output videos.

## Using the teammate's MySQL database

Import the original `database/petlo.sql` into a local MySQL database and ensure it has a real `user_login` row and associated `dogs` rows. Configure the backend environment with a private SQLAlchemy URL such as `mysql+pymysql://USER:PASSWORD@127.0.0.1/petlo`, `PETLO_SEED_DEMO=false`, and the existing `PETLO_LOCAL_USER_ID`. Escape special password characters in the URL. Start Uvicorn with `--env-file backend/.env`; the new `analysis_*` tables are created additively, while legacy `session_statistics` and `session_video` remain untouched.

`database/migrations/20261020_api_extension.sql` is a generated MySQL DDL alternative for those four new tables. It does not import users, modify legacy columns, or calculate physical measurements. Use either the schema initializer or a reviewed migration workflow. The default SQLite flow is integration-tested; a live MySQL connection must still be validated with the teammate's actual server/configuration.

## Analysis modes

`single_view` runs an uploaded front/side tripod video through the existing packet → enhanced detection → dog/disc tracking → joint analysis → v3 events stages. Candidate statistics use the existing pure category/summary functions after the adapter maps that view's episodes. No sample answers or human labels are substituted.

`sample_pair` accepts only the two original matching sample source hashes, one front and one side. The adapter copies verified content to the canonical IDs expected by the existing fusion script. Unknown pairs return 422 before queueing. The original ordinal pairing and provenance validation stay in place. Arbitrary paired recordings are not supported by this mode.

Evidence previews preserve every source frame in the original tool's verified CFR format, used only by the analysis/review stages. Browser playback uses a separate H.264 file with relative original timestamps (`setpts=PTS-STARTPTS`, no frame-rate filter). Event jumps select the matching video's source interval; there is no shared front/side time axis. Missing rates stay null, predictions do not become observations, and ground pickups remain separate from airborne catches.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run test:api
npm run build
.\.venv\Scripts\python.exe -m backend.smoke --video 'PATH\TO\FRONT_VIDEO.mp4' --view front --seconds 0.5
```

Backend unit tests deliberately inject a test-only runner; production uses `PipelineRunner`. The smoke command runs real local FFmpeg/YOLO and every CV stage, then checks media Range responses and persistence after restart. With `--seconds`, it creates a short resized test input and validates plumbing only. Omit `--seconds` to analyze the full supplied video in a new isolated job. These tests do not estimate detection/event accuracy. Output reports go to a new ignored `outputs/backend-smoke-*` folder.

## Deployment boundary

This version rejects non-loopback clients and unlisted browser origins. It is intentionally usable only on the local machine until proper authentication and multi-user access are implemented. Do not expose it with a tunnel, bind publicly, or connect the public Pages site to a user's localhost service. Uploading Python files to GitHub does not run them on Pages. Cloudflare can keep hosting the static frontend; a real remote backend needs a compatible Python runtime, private media storage, persistent job execution, HTTPS, credentials/authorization and production CORS. No remote deployment or Git push is performed here.

## Local presentation tools

Use `scripts/start-local-demo.ps1` from the repository root for a checked loopback-only startup, and `docs/local-demo-checklist.md` for rehearsal. `python -m backend.demo_check --sample-dir PATH` submits the complete original paired samples through the running API, saves a verification record under `outputs/demo-check-*`, and retains the report in the configured local database. This is a real analysis job, not a cached demonstration or an accuracy evaluation.

## Session management and task control

The real API pages support upload-time names, Rename, recoverable Delete/Trash/Restore and Pause/Resume/Stop analysis. Names and deleted_at live in a separate additive table; original identity and reports remain intact. Startup creates this missing table automatically for SQLite/MySQL. The standalone MySQL alternative is `database/migrations/20261021_session_preferences.sql` in addition to the original four-table API migration; live MySQL validation remains pending.

`process_control.py` uses pinned psutil for actual owned CV/FFmpeg process suspension and cancellation. Keep one API worker and the backend running while paused. A paused task holds the worker; cancellation is terminal and requires a new attempt. This does not provide resume-after-reboot or free paused-process RAM. See docs/api-contract.md for lifecycle/endpoint details and docs/local-demo-checklist.md for UI rehearsal. Run the full backend suite to include real parent/child process pause/resume/cancel and pause-aware timeout tests.
