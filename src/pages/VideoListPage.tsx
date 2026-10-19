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
    <section className="page">
      <header className="page-header"><div><h1>Video Management</h1><p>Review your training sessions, throw by throw.</p></div>
     <button
  type="button"
  onClick={() => navigate("/upload")}
  className="button-primary"
>
  Upload video
</button>
      </header>
      <div className="panel table-scroll" tabIndex={0} role="region" aria-label="Training sessions">
      <table>
        <caption className="sr-only">Training session results</caption>
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
              <td data-label="Session">{s.session_id}</td>
              <td data-label="Date">{s.date}</td>
              <td data-label="Throws">{s.throw_count}</td>
              <td data-label="Catches">{s.catch_count}</td>
              <td data-label="Catch rate">{Math.round(s.catch_ratio * 100)}%</td>
              <td data-label="Review">
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
    </section>
  );
}
