import { useEffect, useState } from "react";
import SessionActions from "../components/SessionActions.tsx";
import { defaultSessionName, isTerminalJob } from "../jobLifecycle.ts";
import { Link, useNavigate, useParams } from "react-router";
import { useSessionDetail } from "../hooks/useSessionData.ts";
import { useAnalysisJob } from "../hooks/useAnalysisJob.ts";
import AnalysisStatusCard from "../components/AnalysisStatusCard.tsx";

export default function LiveAnalysisPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [revision, setRevision] = useState(0);
  const { value: session, error } = useSessionDetail(id, String(revision));
  const { job, error: jobError, lastCheckedAt, resume } = useAnalysisJob(session?.current_job_id ?? null, { maxWaitMs: 7_200_000 });
  // The job is the authoritative live state; the detail endpoint supplies its persisted identity.
  const status = job?.status ?? session?.status;
  useEffect(() => { document.title = status === "completed" ? "Report ready · Petlo" : "Analysis status · Petlo"; return () => { document.title = "Petlo"; }; }, [status]);
  return <section className="page"><header className="page-header"><div><h1>Analysis status</h1><p>Your saved task continues independently of this page.</p></div><Link className="button-link" to="/">Video Management</Link></header>
    {error && <div className="analysis-error" role="alert"><p>{error.message}</p><button onClick={() => setRevision(value => value + 1)}>Retry connection</button></div>}
    {!session && !error && <p role="status">Loading saved session…</p>}
    {session && <>
      <p className="analysis-muted">{defaultSessionName(session)} · {session.videos.map(v => v.camera_perspective === "front" ? "Front view" : "Side view").join(" + ")}</p>
      <SessionActions session={session} onChange={() => setRevision(value => value + 1)} onDeleted={() => navigate("/")} />
      {session.current_job_id ? <AnalysisStatusCard job={job} views={session.videos.map(v => v.camera_perspective)} error={jobError} lastCheckedAt={lastCheckedAt} onResume={resume} /> : <div className="panel analysis-card"><h2>No analysis task submitted</h2><p>This saved session may contain an incomplete upload. Return to Upload video to start again.</p></div>}
      <div className="analysis-actions">
        {isTerminalJob(status) && <Link className="button-primary" to={`/sessions/${encodeURIComponent(session.session_id)}`}>{status === "completed" ? "View report" : "Review stopped or failed attempt"}</Link>}
        <Link to="/">Back to video list</Link>
        <Link to="/upload">Upload another video</Link>
      </div>
      <p className="analysis-muted">Refreshing this page only reads the saved task. It does not upload the video again or start a duplicate analysis.</p>
    </>}
  </section>;
}
