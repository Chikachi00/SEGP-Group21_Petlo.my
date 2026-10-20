import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { useSessionHistory } from "../hooks/useSessionData.ts";

export default function LiveHistoryPage() {
  const { sessions, error, loading } = useSessionHistory();
  const completed = sessions.filter(s => s.status === "completed").reverse();
  const data = completed.map(session => ({ date: new Date(session.date).toLocaleString(),
    ratio: session.statistics?.in_air_catch_candidate_rate == null ? null : session.statistics.in_air_catch_candidate_rate * 100 }));
  return <section className="page"><header className="page-header"><div><h1>Historical Trend</h1><p>Air-catch candidate rate across completed sessions; uncertain events are excluded from its denominator.</p></div></header>
    {loading && <p role="status">Loading history…</p>}
    {error && <p role="alert">{error.message}</p>}
    {!loading && !error && completed.length === 0 && <p>No completed analyses yet.</p>}
    <div className="panel chart-panel"><h2>Air-catch candidate rate</h2><div className="chart-frame"><ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}><XAxis dataKey="date" minTickGap={32} /><YAxis domain={[0, 100]} unit="%" /><Tooltip />
        <Line dataKey="ratio" name="Air-catch candidate rate" stroke="#7c83c4" connectNulls={false} />
      </LineChart></ResponsiveContainer></div></div>
    <p>Missing rates remain unknown. These rates describe candidates, not recognition accuracy.</p>
  </section>;
}
