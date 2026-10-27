import JobControlButtons from "./JobControlButtons.tsx";
import { isActiveJob } from "../jobLifecycle.ts";
import { useEffect, useState } from "react";
import type { AnalysisJob } from "../types.ts";
import { analysisSteps, elapsedSeconds, formatElapsed, stageLabel } from "../analysisPresentation.ts";
import "../analysis.css";

function ElapsedTime({ job }: { job: AnalysisJob | null }) {
  const [clock, setClock] = useState(Date.now);
  const active = isActiveJob(job?.status);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return formatElapsed(elapsedSeconds(job, clock));
}

export default function AnalysisStatusCard({ job, views, error, lastCheckedAt, onResume }: {
  job: AnalysisJob | null; views: string[]; error: Error | null;
  lastCheckedAt: number | null; onResume: () => void;
}) {
  const active = isActiveJob(job?.status);
  const steps = analysisSteps(views);
  const position = steps.findIndex(step => step.id === job?.stage);
  return <div className="panel analysis-card">
    <div className="analysis-heading">
      <div><p className="analysis-eyebrow">BACKGROUND ANALYSIS</p><h2>{error ? "Status connection interrupted" : !job ? "Checking saved task" : job.status === "completed" ? "Report ready" : job.status === "failed" ? "Analysis failed" : job.status === "paused" ? "Analysis paused" : job.status === "pausing" ? "Pausing analysis" : job.status === "cancelled" ? "Analysis stopped" : job.status === "cancelling" ? "Stopping analysis" : job.status === "queued" ? "Your task is queued" : "Analyzing your video"}</h2></div>
      <span className={`analysis-badge ${job?.status === "paused" ? "is-paused" : ""} ${error || job?.status === "failed" ? "is-error" : ""}`}>
        {active && job?.status !== "paused" && !error && <span className="analysis-spinner" aria-hidden="true" />}{error ? "Connection issue" : job?.status ?? "Checking"}
      </span>
    </div>
    <p role="status" aria-live="polite">{error ? "The task may still be running. Reconnect to check it; no new analysis will be submitted." : stageLabel(job?.stage)}</p>
    <dl className="analysis-facts"><div><dt>Time since submission</dt><dd><ElapsedTime job={job} /></dd></div>
      <div><dt>Last status check</dt><dd>{lastCheckedAt ? new Date(lastCheckedAt).toLocaleTimeString() : "Waiting"}</dd></div>
      </dl>
    <JobControlButtons job={job} onUpdate={onResume} />
    <details className="analysis-technical"><summary>Technical details</summary><p>Internal task ID: <code>{job?.job_id ?? "Loading…"}</code></p></details>
    {active && !error && <p className="analysis-muted">You can leave this page and return from Video Management. Keep the local backend running. Last status check shows when this page received a response, not how many frames have been processed.</p>}
    {job?.status === "queued" && !error && <p className="analysis-muted">Waiting for the local analysis worker. This computer processes one analysis task at a time.</p>}
    {error && <div className="analysis-error" role="alert"><p>{error.message}</p><button type="button" onClick={onResume}>Resume status checks</button></div>}
    {job?.error && <p className="analysis-error" role="alert">{job.error.message} <small>({job.error.code})</small></p>}
    <details open={active && !error}><summary>Processing stages</summary><ol className="analysis-steps">{steps.map((step, index) => {
      const done = job?.status === "completed" || (position >= 0 && index < position);
      const current = position === index;
      return <li key={step.id} className={done ? "is-done" : current ? "is-current" : ""} aria-current={current ? "step" : undefined}>
        <span aria-hidden="true">{done ? "✓" : index + 1}</span>{step.label}{current && <small>{job?.status === "failed" || job?.status === "cancelled" ? "Stopped here" : job?.status === "paused" ? "Paused here" : "Current stage"}</small>}
      </li>;
    })}</ol></details>
    {active && <p className="analysis-muted">Time since submission includes queueing and pauses. Exact percentage and remaining time are not yet measured. Full videos can take several minutes or longer.</p>}
  </div>;
}
