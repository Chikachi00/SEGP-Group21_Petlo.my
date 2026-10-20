import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { useAnalysisJob } from "../hooks/useAnalysisJob.ts";
import { useSessionDetail } from "../hooks/useSessionData.ts";
import { startAnalysis } from "../api.ts";

export default function LiveResultPage() {
  const { id } = useParams();
  const [revision, setRevision] = useState<string>();
  const { value: session, error } = useSessionDetail(id, revision);
  const [newJob, setNewJob] = useState<{ sessionId: string; jobId: string } | null>(null);
  const observedId = (newJob && newJob.sessionId === id ? newJob.jobId : null) ?? session?.current_job_id ?? null;
  const { job, error: pollingError, isPolling } = useAnalysisJob(observedId);
  useEffect(() => {
    if (job?.status === "completed" || job?.status === "failed") setRevision(`${job.job_id}:${job.status}`);
  }, [job?.job_id, job?.status]);
  const data = session;
  const [selectedVideo, setSelectedVideo] = useState("");
  const [actionError, setActionError] = useState("");
  const [starting, setStarting] = useState(false);
  const retryController = useRef<AbortController | null>(null);
  useEffect(() => () => retryController.current?.abort(), [id]);
  const video = useRef<HTMLVideoElement>(null);
  const playback = data?.videos.find(v => v.video_id === selectedVideo) ?? data?.videos[0];
  const active = isPolling || job?.status === "queued" || job?.status === "running";
  async function retry() {
    if (!data || starting || retryController.current) return;
    const abort = new AbortController(); retryController.current = abort;
    setStarting(true); setActionError("");
    try {
      const next = await startAnalysis(data.session_id, { mode: data.videos.length === 2 ? "sample_pair" : "single_view", video_ids: data.videos.map(v => v.video_id) }, abort.signal);
      abort.signal.throwIfAborted();
      setNewJob({ sessionId: data.session_id, jobId: next.job_id }); setRevision(next.job_id);
    } catch (error) { if (!abort.signal.aborted) setActionError(error instanceof Error ? error.message : String(error)); }
    finally { if (!abort.signal.aborted) setStarting(false); if (retryController.current === abort) retryController.current = null; }
  }
  return <section className="page"><header className="page-header"><div><h1>Result details</h1><p>Session {id}</p></div></header>
    {error && <p role="alert">{error.message}</p>}
    {!data && !error && <p role="status">Loading session…</p>}
    {(pollingError || job?.error) && <p role="alert">{pollingError?.message ?? job?.error?.message}</p>}
    {active && <p role="status">Analysis {job?.status ?? "queued"}: {job?.stage ?? "Waiting"}. Progress: {job?.progress_percent == null ? "not measured" : `${job.progress_percent}%`}</p>}
    {actionError && <p role="alert">{actionError}</p>}
    {data && <>
      {data.status === "failed" && !active && <button type="button" disabled={starting} onClick={() => void retry()}>Start a new analysis attempt</button>}
      <label>Camera view <select value={playback?.video_id ?? ""} onChange={e => setSelectedVideo(e.target.value)}>{data.videos.map(v => <option key={v.video_id} value={v.video_id}>{v.camera_perspective}</option>)}</select></label>
      <div className="panel result-panel">
        {playback?.playback_url ? <video key={playback.video_id} ref={video} src={playback.playback_url} controls width={640} /> : <p>Playback becomes available after successful analysis.</p>}
        <div className="event-panel"><h2>Event candidates</h2><ul className="event-list">{(data.current_job_id === observedId && !active ? data.events : []).map(event => {
          const interval = event.source_intervals.find(i => i.video_id === playback?.video_id);
          return <li key={event.event_id}><button type="button" disabled={!interval || !playback?.playback_url} onClick={() => {
            if (video.current && interval) { video.current.currentTime = interval.start_sec; void video.current.play().catch(() => {}); }
          }}>{event.category.replaceAll("_", " ")}{interval ? ` · ${interval.start_sec.toFixed(3)}–${interval.end_sec.toFixed(3)}s` : " · no interval for this view"}{event.conflict ? " · conflicting views" : ""}</button></li>;
        })}</ul>{data.status === "completed" && data.events.length === 0 && <p>No event candidates were produced. This does not prove there were no throws.</p>}</div>
      </div>
      {data.statistics && data.current_job_id === observedId && !active && <div className="panel"><h2>Candidate statistics</h2>
        <p>Throws: {data.statistics.total_throw_candidates} · Air catches: {data.statistics.candidate_counts.in_air_catch_candidate} · Ground pickups: {data.statistics.candidate_counts.ground_pickup_candidate} · Misses: {data.statistics.candidate_counts.miss_candidate} · Uncertain: {data.statistics.uncertain_events}</p>
        <p>{data.statistics.denominator_definition}</p></div>}
      <ul>{data.limitations.map(text => <li key={text}>{text}</li>)}</ul>
    </>}
  </section>;
}
