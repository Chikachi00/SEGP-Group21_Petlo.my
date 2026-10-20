import { Link } from "react-router";
import { useSessionHistory } from "../hooks/useSessionData.ts";

export default function LiveVideoListPage() {
  const { sessions, error, loading } = useSessionHistory();
  return <section className="page">
    <header className="page-header"><div><h1>Video Management</h1><p>Saved local analysis sessions. Outcomes are unverified candidates.</p></div><Link className="button-primary" to="/upload">Upload video</Link></header>
    {loading && <p role="status">Loading sessions…</p>}
    {error && <p role="alert">{error.message}</p>}
    {!loading && !error && sessions.length === 0 && <p>No saved sessions yet. Upload a video to start.</p>}
    <div className="panel table-scroll"><table><caption>Saved candidate statistics</caption>
      <thead><tr><th>Session</th><th>Date</th><th>Status</th><th>Throw candidates</th><th>Air-catch candidates</th><th>Uncertain</th><th>Air-catch candidate rate</th><th>Review</th></tr></thead>
      <tbody>{sessions.map(session => <tr key={session.session_id}>
        <td>{session.session_id.slice(0, 8)}</td><td>{new Date(session.date).toLocaleString()}</td><td>{session.status}</td>
        <td>{session.statistics?.total_throw_candidates ?? "—"}</td>
        <td>{session.statistics?.candidate_counts.in_air_catch_candidate ?? "—"}</td>
        <td>{session.statistics?.uncertain_events ?? "—"}</td>
        <td>{session.statistics?.in_air_catch_candidate_rate == null ? "—" : `${Math.round(session.statistics.in_air_catch_candidate_rate * 100)}%`}</td>
        <td><Link to={`/sessions/${encodeURIComponent(session.session_id)}`}>Check</Link></td>
      </tr>)}</tbody></table></div>
  </section>;
}
