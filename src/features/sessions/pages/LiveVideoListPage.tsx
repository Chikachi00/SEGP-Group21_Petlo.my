import { useState } from "react";
import { Link } from "react-router";
import { useSessionHistory } from "../hooks/useSessionData.ts";
import SessionActions from "../components/SessionActions.tsx";
import { defaultSessionName, isActiveJob } from "../jobLifecycle.ts";
import "../analysis.css";

export default function LiveVideoListPage() {
  const [trash, setTrash] = useState(false);
  const { sessions, error, loading, refreshing, refresh } = useSessionHistory({ trash });
  const visible = sessions.filter(session => Boolean(session.deleted_at) === trash);
  const active = visible.filter(session => isActiveJob(session.status)).length;
  return <section className="page">
    <header className="page-header"><div><h1>{trash ? "Trash" : "Video Management"}</h1><p>{trash ? "Restore deleted sessions with their saved videos and reports." : `Saved local analyses · ${active} active task${active === 1 ? "" : "s"}. Event outcomes remain candidates.`}</p></div><Link className="button-primary" to="/upload">Upload video</Link></header>
    <div className="analysis-actions"><button disabled={loading || refreshing} onClick={refresh}>Refresh sessions</button><button aria-pressed={trash} onClick={() => setTrash(value => !value)}>{trash ? "Back to sessions" : "Open Trash"}</button>{active > 0 && <span className="analysis-muted">Active sessions refresh every 5 seconds.</span>}</div>
    {loading && <p role="status">Checking saved sessions…</p>}
    {error && <p className="analysis-error" role="alert">{error.message} Previously loaded records may be out of date. Use Refresh sessions to reconnect.</p>}
    {!loading && !refreshing && !error && visible.length === 0 && <p>{trash ? "Trash is empty." : "No saved sessions yet. Upload a video to start."}</p>}
    <div className="panel table-scroll session-table"><table><caption className="sr-only">Saved analysis sessions and candidate statistics</caption>
      <thead><tr><th>Session name</th><th>Date</th><th>Status</th><th>Throws</th><th>Air catches</th><th>Uncertain</th><th>Air-catch candidate rate</th><th>Actions</th></tr></thead>
      <tbody>{visible.map(session => <tr key={session.session_id}>
        <td data-label="Session name" className="session-name">{defaultSessionName(session)}</td><td data-label="Date">{new Date(session.date).toLocaleString()}</td>
        <td data-label="Status"><span className={`analysis-badge ${session.status === "paused" ? "is-paused" : ""}`}>{session.status}</span></td>
        <td data-label="Throws">{session.statistics?.total_throw_candidates ?? "—"}</td>
        <td data-label="Air catches">{session.statistics?.candidate_counts.in_air_catch_candidate ?? "—"}</td>
        <td data-label="Uncertain">{session.statistics?.uncertain_events ?? "—"}</td>
        <td data-label="Candidate rate">{session.statistics?.in_air_catch_candidate_rate == null ? "—" : `${(session.statistics.in_air_catch_candidate_rate * 100).toFixed(1)}%`}</td>
        <td data-label="Actions">{!trash && <Link to={`/sessions/${encodeURIComponent(session.session_id)}${isActiveJob(session.status) ? "/analysis" : ""}`}>{isActiveJob(session.status) ? "View progress" : session.status === "completed" ? "View report" : "Review session"}</Link>}
          <SessionActions session={session} onChange={refresh} /></td>
      </tr>)}</tbody></table></div>
  </section>;
}
