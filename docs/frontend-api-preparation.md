# Frontend API integration — local mode

Updated 2026-10-20. The initial API preparation files are now used by an implemented local backend and a parallel set of real-API pages. Original demo page files remain unchanged.

## Configuration

Copy `.env.example` to `.env.local` on first setup and use:

```dotenv
VITE_USE_API=true
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Restart Vite after editing. With the flag false or absent, the original demo routes remain active. With it true, `src/app/App.tsx` lazy-loads `LiveUploadPage`, `LiveVideoListPage`, `LiveHistoryPage` and `LiveResultPage`. API failures stay visible and never fall back to mock results. Browser configuration is public; no credentials belong in VITE variables.

## Client files

- `src/services/apiClient.ts`: JSON/multipart requests, structured HTTP errors, caller abort and timeout.
- `src/features/videos/api.ts`, `types.ts`: upload one video and its camera perspective.
- `src/features/sessions/api.ts`, `types.ts`: create/list/read sessions, start analysis, read job status, candidate counts/rates and source-specific intervals.
- `src/features/sessions/analysisPolling.ts` and `hooks/useAnalysisJob.ts`: one status request at a time, terminal-state/error handling, request cleanup, and a configurable waiting deadline.
- `src/features/sessions/hooks/useSessionData.ts`: saved-session details and complete paginated history loading.
- `src/config/apiMode.ts`, `src/vite-env.d.ts`: explicit routing/configuration switch.
- `Live*Page.tsx` files under each feature: actual network-backed upload, dog selection/creation, analysis waiting, list/history, candidate events and source-time playback.

Upload and analysis are separate. Unknown upload/analysis progress is not presented as a fake percentage. Stopping browser requests does not cancel an accepted server job. Result pages distinguish request errors from persisted failed jobs, offer a new analysis attempt, and refetch results after completion. Empty/zero-denominator rates remain unknown; the UI calls results candidates.

## Backend and verification

Use [backend/README.md](../backend/README.md) to run the API, and [local-full-stack-testing.md](local-full-stack-testing.md) for the two-terminal setup and human verification procedure. The route contract is [api-contract.md](api-contract.md); current backend status is [backend-handoff.md](backend-handoff.md).

```powershell
npm run test:api
npm run build
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

The client tests isolate HTTP/polling behavior. Backend unit tests use a test-only runner, while `python -m backend.smoke` actually runs FFmpeg/YOLO and existing CV stages. Browser verification also exercises real multipart upload, CORS, persisted jobs and playback. A short clip with no events validates plumbing, not recognition accuracy. The original 108 CV regression tests are run separately.

No commit, push, PR or deployment is performed. Upload source, tests, documents, `.env.example` files, configuration changes and the additive migration while preserving paths. Do not upload runtime databases, private `.env` files, generated output, original videos, models, `node_modules` or `dist`. The Pages site is a static frontend; a publicly usable remote backend still needs its own deployment and authentication.
