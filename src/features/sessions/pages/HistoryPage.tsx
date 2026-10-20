import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface HistoryItem {
  session_id: string;
  date: string;
  throw_count: number;
  catch_count: number;
  catch_ratio: number;
}

export default function HistoryPage() {
  const [history, setHistory] = useState<HistoryItem[]>([]);

  useEffect(() => {
    fetch("/mock/history.json") 
      .then((res) => res.json())
      .then((data) => setHistory(data));
  }, []);

  const chartData = history.map((h) => ({
    date: h.date,
    ratio: Math.round(h.catch_ratio * 100),
  }));

  return (
    <section className="page">
      <header className="page-header"><div><h1>Historical Trend</h1><p>Catch rate across your training sessions.</p></div></header>
      <div className="panel chart-panel">
      <h2>Catch rate</h2>
      <div className="chart-frame"><ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData} margin={{ top: 16, right: 16, bottom: 8, left: 0 }}>
        <XAxis dataKey="date" axisLine={false} tickLine={false} minTickGap={32} tick={{ fill: "#697386", fontSize: 12 }} />
        <YAxis domain={[0, 100]} unit="%" axisLine={false} tickLine={false} width={48} tick={{ fill: "#697386", fontSize: 12 }} />
        <Tooltip />
        <Line type="linear" dataKey="ratio" name="Catch rate" stroke="#7c83c4" strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
      </LineChart>
      </ResponsiveContainer></div></div>
    </section>
  );
}


