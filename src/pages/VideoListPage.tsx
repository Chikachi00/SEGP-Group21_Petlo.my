import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

interface Session {
  session_id: string;
  date: string;
  throw_count: number;
  catch_count: number;
  catch_ratio: number;
}

export default function VideoListPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const navigate = useNavigate(); 

  useEffect(() => {
    fetch("/mock/history.json")
      .then((res) => res.json())
      .then((data) => setSessions(data));
  }, []);

  return (
    <div>
      <h2>Video Management</h2>
      <table border={1} cellPadding={8}>
        <thead>
          <tr>
            <th>Serial number</th>
            <th>Date</th>
            <th>Number of throws</th>
            <th>Number of catches</th>
            <th>Catch rate</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.session_id}>
              <td>{s.session_id}</td>
              <td>{s.date}</td>
              <td>{s.throw_count}</td>
              <td>{s.catch_count}</td>
              <td>{Math.round(s.catch_ratio * 100)}%</td>
              <td>
                {/* Put the session_id from this line into the URL and go to the results page */}
                <button onClick={() => navigate(`/sessions/${s.session_id}`)}>
                  Check
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}