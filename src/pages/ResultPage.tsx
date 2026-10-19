import { useRef } from "react";
import { useParams } from "react-router";

const events = [
  { id: 1, time: 5.2, label: "00:05 · Catch" },
  { id: 2, time: 18.0, label: "00:18 · Failure" },
  { id: 3, time: 31.0, label: "00:31 · Catch" },
  { id: 4, time: 47.3, label: "00:47 · Indetermination" },
];

export default function ResultPage() {
  const { id } = useParams();
  
  const videoRef = useRef<HTMLVideoElement>(null);

  function jumpTo(time: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = time;
    videoRef.current.play();
  }

  return (
    <section className="page">
      <header className="page-header"><div><h1>Result details</h1>
      <p>Training session · {id}</p></div></header>
      <div className="panel result-panel">

      <video ref={videoRef} src="/test_video.mp4" controls width={480} />

      <div className="event-panel"><h2>Session events</h2><ul className="event-list">
        {events.map((ev) => (
          <li key={ev.id}><button onClick={() => jumpTo(ev.time)} aria-label={`Play event ${ev.id}: ${ev.label}`}>
            <span className="event-number">{ev.id}</span> {ev.label}<span aria-hidden="true"> →</span></button>
          </li>
        ))}
      </ul></div></div>
    </section>
  );
}
