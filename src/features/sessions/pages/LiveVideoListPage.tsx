import { Link } from "react-router";
import { useSessionHistory } from "../hooks/useSessionData.ts";
import "../analysis.css";

export default function LiveVideoListPage() {
  const { sessions, error, loading, refreshing, refresh } = useSessionHistory();
  const active = sessions.filter(session => session.status === "running" || session.status === "queued").length;
  return <section className="page">
    <header className="page-header"><div><h1>Video Management</h1><p>Saved local analyses · {active} active task{active === 1 ? "" : "s"}. Event outcomes remain candidates.</p></div><Link className="button-primary" to="/upload">Upload video</Link></header>
    <div className="analysis-actions"><button disabled={loading || refreshing} onClick={refresh}>Refresh sessions</button>{active > 0 && <span className="analysis-muted">Active sessions refresh every 5 seconds.</span>}</div>
    {loading && <p role="status">Checking saved sessions…</p>}
    {error && <p className="analysis-error" role="alert">{error.message} Previously loaded records may be out of date. Use Refresh sessions to reconnect.</p>}
    {!loading && !error && sessions.length === 0 && <p>No saved sessions yet. Upload a video to start.</p>}
    <div className="panel table-scroll"><table><caption className="sr-only">Saved analysis sessions and candidate statistics</caption>
      <thead><tr><th>Session</th><th>Date</th><th>Status</th><th>Throw candidates</th><th>Air catches</th><th>Uncertain</th><th>Air-catch candidate rate</th><th>Review</th></tr></thead>
      <tbody>{sessions.map(session => {
        const pending = session.status === "running" || session.status === "queued";
        return <tr key={session.session_id}>
          <td data-label="Session" title={session.session_id}>{session.session_id.slice(0, 8)}</td><td data-label="Date">{new Date(session.date).toLocaleString()}</td>
          <td data-label="Status"><span className="analysis-badge">{session.status}</span></td>
          <td data-label="Throw candidates">{session.statistics?.total_throw_candidates ?? "—"}</td>
          <td data-label="Air catches">{session.statistics?.candidate_counts.in_air_catch_candidate ?? "—"}</td>
          <td data-label="Uncertain">{session.statistics?.uncertain_events ?? "—"}</td>
          <td data-label="Candidate rate">{session.statistics?.in_air_catch_candidate_rate == null ? "—" : `${(session.statistics.in_air_catch_candidate_rate * 100).toFixed(1)}%`}</td>
          <td data-label="Review"><Link to={`/sessions/${encodeURIComponent(session.session_id)}${pending ? "/analysis" : ""}`}>{pending ? "View progress" : session.status === "completed" ? "View report" : "Review session"}</Link></td>
        </tr>;
      })}</tbody></table></div>
  </section>;
}
