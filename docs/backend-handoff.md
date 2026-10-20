# Backend integration status — 2026-10-20

The local backend is now implemented in `backend/`; it is no longer only a teammate checklist. Follow [the backend README](../backend/README.md) and [the local full-stack testing guide](local-full-stack-testing.md) to run it. [api-contract.md](api-contract.md) describes the implemented local interface.

## Implemented locally

- FastAPI endpoints for dog records, session create/list/detail, streamed multipart video upload, analysis start, job status, and Range-capable H.264 playback.
- SQLite development persistence plus SQLAlchemy mappings compatible with the original MySQL `dogs`, `user_login`, and `video` tables. Additive `analysis_*` tables store session lifecycle, precise video metadata, jobs, statistics and per-view event intervals. The original SQL file is unchanged.
- One local background inference worker. Session state changes reject duplicate starts; results become completed only after transactionally saving the job, events and metadata. Interrupted jobs fail explicitly after restart.
- The original source packet, verified evidence preview, detector, dog/disc tracker, joint analysis and v3 event scripts are invoked without algorithm edits. Sources and outputs are isolated per job; subprocess arguments are not assembled as a shell command.
- Single-view event adaptation reuses the existing candidate mapping/statistics functions. Sample-pair fusion validates the two known source hashes and never loads human-answer labels.
- Explicit frontend API mode, dog selection/creation, actual upload requests, background job polling, session/history/results pages, and source-specific seek times. The original mock/demo pages remain selectable.

## Remaining before public deployment

The service is currently loopback-only and uses a configured local user; it is not a login/authentication implementation. Public hosting needs actual user authentication, authorization/account workflows, secure remote media storage, job lifecycle/retention/resource limits, a durable production worker service, HTTPS and production CORS configuration. The existing static Pages deployment does not automatically run this Python backend.

Validate the MySQL URL, existing user/dog records, character sets and new table permissions on the teammate's actual MySQL server. The development flow and tests use SQLite; generated MySQL DDL is not evidence of a tested live MySQL connection. `create_all` only creates missing tables and does not reconcile incompatible existing schemas.

General paired-camera matching/synchronization and reliable new-video event recognition remain algorithm work. The current sample-pair mode deliberately rejects unrelated recordings. Camera calibration is still required for physical distances, heights and speeds. Candidate statistics are not accuracy estimates.

All code changes remain local for the user to upload manually. Runtime databases, uploads, generated videos, model weights, environment secrets and test outputs stay outside Git.
