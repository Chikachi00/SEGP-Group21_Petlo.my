import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";

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
    <div>
      <h2>Historical Trend</h2>
      <LineChart width={600} height={300} data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" />
        <YAxis domain={[0, 100]} unit="%" />
        <Tooltip />
        <Line type="monotone" dataKey="ratio" name="Catch rate" stroke="#4f46e5" />
      </LineChart>
      <div>
        table
      </div>
    </div>
  );
}