import { useEffect, useState } from "react";
import type { AnalysisJob } from "../types.ts";
import { analysisSteps, elapsedSeconds, formatElapsed, stageLabel } from "../analysisPresentation.ts";
import "../analysis.css";

export default function AnalysisStatusCard({ job, views, error, lastCheckedAt, onResume }: {
  job: AnalysisJob | null; views: string[]; error: Error | null;
  lastCheckedAt: number | null; onResume: () => void;
}) {
  const [clock, setClock] = useState(Date.now);
  const active = job?.status === "running" || job?.status === "queued";
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  const steps = analysisSteps(views);
  const position = steps.findIndex(step => step.id === job?.stage);
  return <div className="panel analysis-card">
    <div className="analysis-heading">
      <div><p className="analysis-eyebrow">BACKGROUND ANALYSIS</p><h2>{error ? "Status connection interrupted" : !job ? "Checking saved task" : job.status === "completed" ? "Report ready" : job.status === "failed" ? "Analysis failed" : job.status === "queued" ? "Your task is queued" : "Analyzing your video"}</h2></div>
      <span className={`analysis-badge ${error || job?.status === "failed" ? "is-error" : ""}`}>
        {active && !error && <span className="analysis-spinner" aria-hidden="true" />}{error ? "Connection issue" : job?.status ?? "Checking"}
      </span>
    </div>
    <p role="status" aria-live="polite">{error ? "The task may still be running. Reconnect to check it; no new analysis will be submitted." : stageLabel(job?.stage)}</p>
    <dl className="analysis-facts"><div><dt>Time since submission</dt><dd>{formatElapsed(elapsedSeconds(job, clock))}</dd></div>
      <div><dt>Last status check</dt><dd>{lastCheckedAt ? new Date(lastCheckedAt).toLocaleTimeString() : "Waiting"}</dd></div>
      <div><dt>Task ID</dt><dd className="analysis-id">{job?.job_id ?? "Loading…"}</dd></div></dl>
    {active && !error && <p className="analysis-muted">You can leave this page and return from Video Management. Keep the local backend running. Last status check shows when this page received a response, not how many frames have been processed.</p>}
    {job?.status === "queued" && !error && <p className="analysis-muted">Waiting for the local analysis worker. This computer processes one analysis task at a time.</p>}
    {error && <div className="analysis-error" role="alert"><p>{error.message}</p><button type="button" onClick={onResume}>Resume status checks</button></div>}
    {job?.error && <p className="analysis-error" role="alert">{job.error.message} <small>({job.error.code})</small></p>}
    <details open={active && !error}><summary>Processing stages</summary><ol className="analysis-steps">{steps.map((step, index) => {
      const done = job?.status === "completed" || (position >= 0 && index < position);
      const current = position === index;
      return <li key={step.id} className={done ? "is-done" : current ? "is-current" : ""} aria-current={current ? "step" : undefined}>
        <span aria-hidden="true">{done ? "✓" : index + 1}</span>{step.label}{current && <small>{job?.status === "failed" ? "Stopped here" : "Current stage"}</small>}
      </li>;
    })}</ol></details>
    {active && <p className="analysis-muted">Exact percentage and remaining time are not yet measured. Full videos can take several minutes or longer.</p>}
  </div>;
}
