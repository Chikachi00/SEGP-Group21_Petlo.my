
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer
} from "recharts";

interface HistoryItem {
  session_id: string;
  date: string;
  throw_count: number;
  catch_count: number;
  catch_ratio: number;
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/mock/history.json")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load history");
        return res.json();
      })
      .then((data) => {
        if (!Array.isArray(data)) {
          throw new Error("History data must be an array");
        }
        setHistory(data);
      })
      .catch(() => setError("Unable to load training history."))
      .finally(() => setLoading(false));
  }, []);

  const chartData = history.map((h) => ({
    date: h.date,
    ratio: Math.round(h.catch_ratio * 100),
  }));

  return (
    <main className="history-page">
      <nav className="history-nav">
        <span>🐾 Disc Dog Tracker</span>
        <button onClick={() => navigate("/")}>
          ← Back to Dashboard
        </button>
      </nav>

      <div className="history-content">
        <p className="history-label">TRAINING ANALYTICS</p>
        <h1>Historical Trend</h1>
        <p className="history-subtitle">
          Track your catch rate and training progress over time.
        </p>

        <section className="history-card">
          <h2>Catch Rate Trend</h2>
          <p>Your recent training performance</p>

          {loading ? (
            <div className="history-message">Loading history...</div>
          ) : error ? (
            <div className="history-message">{error}</div>
          ) : chartData.length === 0 ? (
            <div className="history-message">
              No training history available.
            </div>
          ) : (
            <div className="history-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={chartData}
                  margin={{ top: 20, right: 25, bottom: 10, left: 0 }}
                >
                  <CartesianGrid
                    stroke="#ffffff20"
                    strokeDasharray="3 3"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    stroke="#dce5f0"
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    domain={[0, 100]}
                    unit="%"
                    stroke="#dce5f0"
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="ratio"
                    name="Catch rate"
                    stroke="#ffffff"
                    strokeWidth={3}
                    dot={{ fill: "#ffffff", r: 5 }}
                    activeDot={{ r: 7 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
