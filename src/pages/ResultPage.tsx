import { useRef } from "react";
import { useNavigate, useParams } from "react-router";
import PawLogo from "../components/PawLogo";

const events = [
  { id: 1, time: 5.2, label: "00:05 · Catch" },
  { id: 2, time: 18.0, label: "00:18 · Failure" },
  { id: 3, time: 31.0, label: "00:31 · Catch" },
  { id: 4, time: 47.3, label: "00:47 · Indetermination" },
];

export default function ResultPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);

  function jumpTo(time: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = time;
    void videoRef.current.play().catch(() => {});
  }

  return (
    <main className="result-page">
      <nav className="result-nav">
        <div className="result-brand">
          <PawLogo />
          <span>Disc Dog Tracker</span>
        </div>

        <button
          className="result-back"
          onClick={() => navigate("/")}
        >
          ← Back to Dashboard
        </button>
      </nav>

        <div
          className="result-content"
          style={{ transform: "translateY(-60px)" }}
        >
        <p className="result-label">TRAINING ANALYTICS</p>
        <h1>Result Details</h1>
        <p className="result-subtitle">
          Training session · {id}
        </p>

        <div className="result-grid">
          <section className="result-card">
            <h2>Training Video</h2>
            <p>Review your recorded training session.</p>

            <video
              ref={videoRef}
              src="/test_video.mp4"
              controls
              playsInline
              className="result-video"
            />
          </section>

          <section className="result-card">
            <h2>Session Events</h2>
            <p>Click an event to jump to that moment.</p>

            <div className="result-events">
              {events.map((ev) => (
                <button
                  key={ev.id}
                  className="result-event"
                  onClick={() => jumpTo(ev.time)}
                  aria-label={`Play event ${ev.id}: ${ev.label}`}
                >
                  <span className="result-event-number">
                    {ev.id}
                  </span>

                  <span>{ev.label}</span>

                  <span className="result-event-arrow">
                    ▶
                  </span>
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
