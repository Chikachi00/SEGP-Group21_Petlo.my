import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useAnalysisJob } from "../hooks/useAnalysisJob.ts";
import { useSessionDetail } from "../hooks/useSessionData.ts";
import { startAnalysis } from "../api.ts";
import AnalysisStatusCard from "../components/AnalysisStatusCard.tsx";
import { downloadReport } from "../reportExport.ts";

export default function LiveResultPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [revision, setRevision] = useState<string>();
  const { value: data, error } = useSessionDetail(id, revision);
  const { job, error: pollingError, isPolling, lastCheckedAt, resume } = useAnalysisJob(data?.current_job_id ?? null);
  useEffect(() => {
    if (job?.status === "completed" || job?.status === "failed") setRevision(`${job.job_id}:${job.status}`);
  }, [job?.job_id, job?.status]);
  const [selectedVideo, setSelectedVideo] = useState("");
  const [actionError, setActionError] = useState("");
  const [starting, setStarting] = useState(false);
  const retryController = useRef<AbortController | null>(null);
  useEffect(() => () => retryController.current?.abort(), [id]);
  const video = useRef<HTMLVideoElement>(null);
  const playback = data?.videos.find(v => v.video_id === selectedVideo) ?? data?.videos[0];
  const status = job?.status ?? data?.status;
  const active = status === "queued" || status === "running";
  const reportReady = data?.status === "completed" && status === "completed" && data.current_job_id === job?.job_id;
  async function retry() {
    if (!data || starting || retryController.current || isPolling || active || pollingError) return;
    const abort = new AbortController(); retryController.current = abort;
    setStarting(true); setActionError("");
    try {
      await startAnalysis(data.session_id, { mode: data.videos.length === 2 ? "sample_pair" : "single_view", video_ids: data.videos.map(v => v.video_id) }, abort.signal);
      abort.signal.throwIfAborted();
      navigate(`/sessions/${encodeURIComponent(data.session_id)}/analysis`);
    } catch (error) { if (!abort.signal.aborted) setActionError(error instanceof Error ? error.message : String(error)); }
    finally { if (!abort.signal.aborted) setStarting(false); if (retryController.current === abort) retryController.current = null; }
  }
  const rate = (value: number | null | undefined) => value == null ? "Unknown" : `${(value * 100).toFixed(1)}%`;
  return <section className="page"><header className="page-header"><div><h1>Analysis report</h1><p>Session {id} · Machine event candidates for manual review</p></div><Link to="/">Video Management</Link></header>
    {error && <div className="analysis-error" role="alert"><p>{error.message}</p><button onClick={() => setRevision(String(Date.now()))}>Retry connection</button></div>}
    {!data && !error && <p role="status">Loading session…</p>}
    {actionError && <p className="analysis-error" role="alert">{actionError}</p>}
    {data && <>
      {(active || pollingError || status === "failed") && <AnalysisStatusCard job={job} views={data.videos.map(v => v.camera_perspective)} error={pollingError} lastCheckedAt={lastCheckedAt} onResume={resume} />}
      {active && <div className="analysis-actions"><Link className="button-primary" to={`/sessions/${encodeURIComponent(data.session_id)}/analysis`}>Open analysis status</Link></div>}
      {status === "failed" && <div className="analysis-actions"><button type="button" disabled={starting || isPolling || Boolean(pollingError)} onClick={() => void retry()}>Start a new analysis attempt</button></div>}
      {!data.current_job_id && <p>No analysis was submitted for this session. Return to Upload video to start a complete submission.</p>}
      {reportReady && data.statistics && <>
        <div className="report-metrics">{[
          ["Throw candidates", data.statistics.total_throw_candidates], ["Air-catch candidates", data.statistics.candidate_counts.in_air_catch_candidate],
          ["Ground-pickup candidates", data.statistics.candidate_counts.ground_pickup_candidate], ["Uncertain", data.statistics.uncertain_events],
        ].map(([label, count]) => <div className="panel report-metric" key={label}><h2>{label}</h2><strong>{count}</strong></div>)}</div>
        <div className="panel report-summary"><h2>Candidate statistics</h2>
          <p>Air-catch candidate rate: <strong>{rate(data.statistics.in_air_catch_candidate_rate)}</strong> · Retrieval candidate rate: <strong>{rate(data.statistics.retrieval_candidate_rate)}</strong> · Classified candidate coverage: <strong>{rate(data.statistics.candidate_coverage)}</strong></p>
          <p>Miss candidates: {data.statistics.candidate_counts.miss_candidate} · Classified candidates: {data.statistics.classified_candidate_events}</p>
          <p className="analysis-muted">{data.statistics.denominator_definition} These are candidate rates, not recognition accuracy.</p>
          <div className="analysis-actions"><button onClick={() => downloadReport(data, "json")}>Download report JSON</button><button onClick={() => downloadReport(data, "csv")}>Download events CSV</button></div>
          <p className="analysis-muted">CSV contains one row per event and camera view. Matching views share the same event ID.</p>
          <p className="analysis-muted">Algorithm: {data.algorithm_version ?? "Not recorded"}</p>
        </div>
      </>}
      <label>Camera view <select value={playback?.video_id ?? ""} onChange={e => { setSelectedVideo(e.target.value); setActionError(""); }}>{data.videos.map(v => <option key={v.video_id} value={v.video_id}>{v.camera_perspective === "front" ? "Front view" : "Side view"}</option>)}</select></label>
      <div className="panel result-panel">
        {playback?.playback_url && reportReady ? <video key={playback.video_id} ref={video} src={playback.playback_url} controls preload="metadata" width={640} onError={() => setActionError("Video playback failed. Check that the backend is still running, then reload this page.")} /> : <p>Playback becomes available after successful analysis.</p>}
        <div className="event-panel"><h2>Event candidates</h2><p className="analysis-muted">Choose an event to play its source interval in the selected view.</p><ul className="event-list">{(reportReady ? data.events : []).map((event, index) => {
          const interval = event.source_intervals.find(i => i.video_id === playback?.video_id);
          return <li key={event.event_id}><button type="button" disabled={!interval || !playback?.playback_url} onClick={() => {
            if (video.current && interval) { video.current.currentTime = interval.start_sec; void video.current.play().catch(() => {}); }
          }}><span className="event-number">{String(index + 1).padStart(2, "0")}</span><span>{event.category.replaceAll("_", " ")}{event.conflict ? " · conflicting views" : ""}</span><span>{interval ? `${interval.start_sec.toFixed(3)}–${interval.end_sec.toFixed(3)}s` : "No interval for this view"}</span></button></li>;
        })}</ul>{reportReady && data.events.length === 0 && <p>No event candidates were produced. This does not prove there were no throws.</p>}</div>
      </div>
      {data.limitations.length > 0 && <details className="panel report-summary"><summary>Analysis limitations</summary><ul>{data.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>}
    </>}
  </section>;
}
