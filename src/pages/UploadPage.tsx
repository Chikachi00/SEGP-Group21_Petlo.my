import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import "./UploadPage.css";

type Status = "idle" | "uploading" | "analyzing" | "complete" | "cancelled";

export default function UploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  const busy = status === "uploading" || status === "analyzing";

  useEffect(() => {
    if (status !== "uploading") return;

    const timer = window.setInterval(() => {
      setProgress((value) => Math.min(value + 2, 100));
    }, 400);

    return () => window.clearInterval(timer);
  }, [status]);

  useEffect(() => {
    if (status === "uploading" && progress === 100) {
      setStatus("analyzing");
    }
  }, [status, progress]);

  useEffect(() => {
    if (status !== "analyzing") return;

    const timer = window.setTimeout(() => {
      setStatus("complete");
    }, 2500);

    return () => window.clearTimeout(timer);
  }, [status]);

  function startUpload() {
    if (!file) return;
    setProgress(0);
    setStatus("uploading");
  }

  const titles: Record<Status, string> = {
    idle: "Ready to upload your video",
    uploading: "Uploading your video…",
    analyzing: "Analyzing your session…",
    complete: "Your demo session is ready",
    cancelled: "Upload cancelled",
  };

  const messages: Record<Status, string> = {
    idle: "Choose a training video to get started.",
    uploading: "Please keep this page open while your video uploads.",
    analyzing: "Demo: identifying throws and catches in your video.",
    complete: "The waiting-page demo is complete.",
    cancelled: "You can restart the demo or choose another video.",
  };

  const badges: Record<Status, string> = {
    idle: "Ready",
    uploading: "In progress",
    analyzing: "In progress",
    complete: "Complete",
    cancelled: "Cancelled",
  };

  const stages: Record<Status, string> = {
    idle: "Waiting for video",
    uploading: "Uploading video",
    analyzing: "Upload complete · Demo analysis",
    complete: "Demo complete",
    cancelled: "Demo stopped",
  };

  const activeStep =
    status === "complete"
      ? 3
      : status === "analyzing"
        ? 1
        : status === "uploading"
          ? 0
          : -1;

  return (
    <section className="upload-page">
      <div className="upload-breadcrumb">
        <button type="button" onClick={() => navigate("/")}>
          Video Management
        </button>
        <span>/</span>
        <span>Upload video</span>
      </div>

      <h1>Upload video</h1>
      <p className="upload-subtitle">
        Your next training session, ready for review.
      </p>

      <div className="upload-card">
        <div className="upload-card-top">
          <span className="upload-context">New training session</span>
          <span className="upload-badge">{badges[status]}</span>
        </div>

        <div className="upload-center">
          <div className="upload-icon">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              aria-hidden="true"
            >
              <path d="M12 16V3m-5 5 5-5 5 5M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" />
            </svg>
          </div>

          <h2>{titles[status]}</h2>
          <p aria-live="polite">{messages[status]}</p>
        </div>

        <div className="upload-file">
          <span className="upload-file-icon" aria-hidden="true">
            ▤
          </span>
          <div className="upload-file-details">
            <div className="upload-filename">
              {file ? file.name : "No video selected"}
            </div>
            <div className="upload-file-size">
              {file
                ? `${(file.size / 1024 / 1024).toFixed(1)} MB · Local preview only`
                : "Choose a video below · Demo"}
            </div>
          </div>
        </div>

        <div className="upload-progress-label">
          <span>{stages[status]}</span>
          <strong>{progress}%</strong>
        </div>

        <div
          className="upload-track"
          role="progressbar"
          aria-label="Demo upload progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <div
            className="upload-bar"
            style={{ width: `${progress}%` }}
          />
        </div>

        <div className="upload-steps">
          {["Upload video", "Analyze session", "Ready to review"].map(
            (label, index) => (
              <div
                key={label}
                className={`upload-step ${
                  index < activeStep
                    ? "is-done"
                    : index === activeStep
                      ? "is-active"
                      : ""
                }`}
              >
                <span className="upload-dot">
                  {index < activeStep ? "Done" : index + 1}
                </span>
                <span>{label}</span>
              </div>
            ),
          )}
        </div>

        <div className="upload-footer">
          <span className="upload-hint">
            Longer videos may take a little more time.
          </span>

          {busy ? (
            <button
              className="upload-button"
              type="button"
              onClick={() => setStatus("cancelled")}
            >
              Cancel upload
            </button>
          ) : (
            <button
              className="upload-button upload-button-primary"
              type="button"
              disabled={!file}
              onClick={startUpload}
            >
              {status === "cancelled"
                ? "Try again"
                : status === "complete"
                  ? "Replay demo"
                  : "Start demo upload"}
            </button>
          )}
        </div>
      </div>

      <div className="upload-demo">
        <span>Interactive demo · No files are sent to a server.</span>
        <label
          className={`upload-choose ${busy ? "is-disabled" : ""}`}
        >
          Choose video
          <input
            type="file"
            accept="video/*"
            disabled={busy}
            onChange={(event) => {
              const selected = event.target.files?.[0];
              if (!selected) return;

              if (!selected.type.startsWith("video/")) {
                setError("Please choose a video file.");
                event.target.value = "";
                return;
              }

              setError("");
              setFile(selected);
              setProgress(0);
              setStatus("idle");
            }}
          />
        </label>
      </div>

      {error && (
        <p className="upload-error" role="alert">
          {error}
        </p>
      )}

      <p className="upload-note">
        Track every throw. Celebrate every catch.
      </p>
    </section>
  );
}
