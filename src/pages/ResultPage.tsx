
import { useRef } from "react";
import { useNavigate, useParams } from "react-router";
import PawLogo from "../components/PawLogo";

const events = [
  { id: 1, time: 4, type: "Catch" },
  { id: 2, time: 13, type: "Failure" },
  { id: 3, time: 24.5, type: "Catch" },
  { id: 4, time: 34, type: "Catch" },
];

export default function ResultPage() {
  const { id = "s_001" } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);

    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  };

  const jumpToEvent = (time: number) => {
    const video = videoRef.current;
    if (!video) return;

    video.currentTime = Math.max(0, time - 0.5);
    void video.play().catch(() => {});
  };

  return (
    <div className="result-page">
      <header className="result-nav">
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
      </header>

      <main className="result-content">
        <div style={{ transform: "translateY(-60px)" }}>
          <p className="result-label">
            TRAINING ANALYTICS
          </p>

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
                src="/new-video.mp4.mp4"
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
                    onClick={() => jumpToEvent(ev.time)}
                  >
                    <span className="result-event-number">
                      {ev.id}
                    </span>

                    <span>
                      {formatTime(ev.time)} · {ev.type}
                    </span>

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
    </div>
  );
}
