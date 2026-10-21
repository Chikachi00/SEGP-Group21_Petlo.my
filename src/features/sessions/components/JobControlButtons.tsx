import { useEffect, useRef, useState } from "react";
import { controlAnalysisJob } from "../api.ts";
import type { AnalysisJob } from "../types.ts";
import { isActiveJob } from "../jobLifecycle.ts";

export default function JobControlButtons({ job, onUpdate }: { job: AnalysisJob | null; onUpdate: () => void }) {
  const [busy, setBusy] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function request(action: "pause" | "resume" | "cancel") {
    if (!job || controller.current) return;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError("");
    try {
      await controlAnalysisJob(job.job_id, action, abort.signal);
      if (!abort.signal.aborted) { setConfirmStop(false); onUpdate(); }
    } catch (error) {
      if (!abort.signal.aborted) { setError(error instanceof Error ? error.message : String(error)); onUpdate(); }
    } finally {
      if (!abort.signal.aborted) setBusy(false);
      if (controller.current === abort) controller.current = null;
    }
  }
  if (!job || !isActiveJob(job.status)) return null;
  return <div className="job-controls" aria-busy={busy}>
    <div className="analysis-actions">
      {(job.status === "queued" || job.status === "running") && <button disabled={busy} onClick={() => void request("pause")}>Pause analysis</button>}
      {job.status === "paused" && <button className="button-primary" disabled={busy} onClick={() => void request("resume")}>Resume analysis</button>}
      {job.status === "pausing" && <button disabled>Pausing…</button>}
      {job.status === "cancelling" ? <button disabled>Stopping analysis…</button> : <button className="session-danger" disabled={busy} onClick={() => setConfirmStop(true)}>Stop analysis</button>}
    </div>
    {confirmStop && job.status !== "cancelling" && <div className="session-confirm" role="dialog" aria-label="Stop this analysis?">
      <p>Stop this analysis? It cannot continue from the same process afterwards. Uploaded videos are kept for a new attempt.</p>
      <button className="session-danger" disabled={busy} onClick={() => void request("cancel")}>Confirm stop</button><button disabled={busy} onClick={() => setConfirmStop(false)}>Keep analyzing</button>
    </div>}
    {job.status === "paused" && <p className="analysis-muted">Analysis is paused. Keep the backend running to resume this process. Other queued tasks wait for this worker.</p>}
    {busy && <p role="status">Sending task control…</p>}
    {error && <p className="analysis-error" role="alert">{error}</p>}
  </div>;
}
