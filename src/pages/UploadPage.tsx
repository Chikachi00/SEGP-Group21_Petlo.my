import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import "./UploadPage.css";
import PawLogo from "../components/PawLogo";

type Status = "idle" | "uploading" | "analyzing" | "complete" | "cancelled";

export default function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const busy = status === "uploading" || status === "analyzing";

  useEffect(() => {
    if (status !== "uploading") return;

    const timer = window.setInterval(() => {
      setProgress((p) => Math.min(p + 2, 100));
    }, 100);

    return () => window.clearInterval(timer);
  }, [status]);

  useEffect(() => {
    if (status === "uploading" && progress >= 100) {
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

  function chooseFile(selected?: File) {
    if (!selected) return;

    const extension = selected.name.split(".").pop()?.toLowerCase();
    if (!["mp4", "mov", "webm"].includes(extension || "")) {
      setError("Please select an MP4, MOV or WebM video.");
      return;
    }

    setFile(selected);
    setError("");
    setProgress(0);
    setStatus("idle");
  }

  function startUpload() {
    if (!file) return;
    setError("");
    setProgress(0);
    setStatus("uploading");
  }

  function cancelUpload() {
    setStatus("cancelled");
    setProgress(0);
  }

  const titles: Record<Status, string> = {
    idle: "Upload your training video",
    uploading: "Uploading your video...",
    analyzing: "Analyzing your session...",
    complete: "Your demo session is ready!",
    cancelled: "Upload cancelled",
  };

  const descriptions: Record<Status, string> = {
    idle: "Choose a video to begin your training review.",
    uploading: "Preparing your video for analysis.",
    analyzing: "Simulating throw and catch recognition.",
    complete: "Your frontend demo has finished successfully.",
    cancelled: "Choose another video or try again.",
  };

  const steps = ["Upload Video", "Analyze Session", "View Results"];
  const activeStep =
    status === "complete" ? 3 :
    status === "analyzing" ? 1 :
    status === "uploading" ? 0 : -1;

  return (
    <div className="upload-page">
      <header className="upload-navbar">
        
        <button
          className="upload-brand"
          onClick={() => navigate("/")}
        >
          <PawLogo />
          <span>Disc Dog Tracker</span>
        </button>


        <button
          className="upload-back"
          onClick={() => navigate("/")}
        >
          ← Back to Dashboard
        </button>
      </header>

      <main className="upload-container">
        <div className="upload-heading">
          <span className="upload-eyebrow">
            <span className="upload-accent-line" />
            DISC DOG TRAINING ANALYTICS
          </span>

          <h1>Upload Training Video</h1>
          <p>
            Every great catch starts with a throw.
            <br />
            Review your training performance.
          </p>
        </div>

        <section className="upload-new-card">
          <div className="upload-card-header">
            <span>NEW TRAINING SESSION</span>
            <span className="upload-status">
              <span className={`upload-status-dot ${status}`} />
              {status === "idle" ? "Ready" :
               status === "complete" ? "Complete" :
               status === "cancelled" ? "Cancelled" :
               "In Progress"}
            </span>
          </div>

          <div
            className={`upload-dropzone ${busy ? "is-busy" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!busy) chooseFile(e.dataTransfer.files[0]);
            }}
          >
            <div className="upload-large-icon">
              {status === "complete" ? "✓" :
               status === "analyzing" ? "◌" : "↑"}
            </div>

            <h2>{titles[status]}</h2>
            <p aria-live="polite">{descriptions[status]}</p>

            {!busy && status !== "complete" && (
              <button
                className="upload-select-button"
                onClick={() => inputRef.current?.click()}
              >
                Choose Video
              </button>
            )}

            <input
              ref={inputRef}
              type="file"
              accept=".mp4,.mov,.webm,video/*"
              hidden
              disabled={busy}
              onChange={(e) => {
                chooseFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />

            <span className="upload-format">
              MP4, MOV, WebM · Frontend demonstration
            </span>
          </div>

          {file && (
            <div className="upload-selected-file">
              <span className="upload-file-symbol">▣</span>
              <div>
                <strong>{file.name}</strong>
                <small>
                  {(file.size / 1024 / 1024).toFixed(1)} MB
                  {" · "}Local file selected
                </small>
              </div>
              <span className="upload-file-check">✓</span>
            </div>
          )}

          {(status !== "idle" || file) && (
            <div className="upload-progress-section">
              <div className="upload-progress-heading">
                <span>
                  {status === "analyzing" ? "Demo analysis in progress" :
                   status === "complete" ? "Demo complete" :
                   status === "cancelled" ? "Demo cancelled" :
                   "Simulated upload progress"}
                </span>
                <strong>{progress}%</strong>
              </div>
              <div
                className="upload-progress-track"
                role="progressbar"
                aria-valuenow={progress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Simulated upload progress"
              >
                <div
                  className="upload-progress-fill"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          <div className="upload-step-list">
            {steps.map((label, index) => {
              const done = index < activeStep;
              const current = index === activeStep;
              return (
                <div
                  key={label}
                  className={`upload-step ${done ? "done" : ""} ${current ? "current" : ""}`}
                >
                  <span className="upload-step-number">
                    {done ? "✓" : index + 1}
                  </span>
                  <span>{label}</span>
                </div>
              );
            })}
          </div>

          <div className="upload-actions">
            {busy ? (
              <button className="upload-cancel" onClick={cancelUpload}>
                Cancel Demo
              </button>
            ) : status === "complete" ? (
              <button
                className="upload-main-button"
                onClick={() => navigate("/result/s_001")}
              >
                View Demo Result →
              </button>
            ) : (
              <button
                className="upload-main-button"
                disabled={!file}
                onClick={startUpload}
              >
                {status === "cancelled"
                  ? "Try Again"
                  : "Start Demo Upload →"}
              </button>
            )}
          </div>
        </section>

        {error && <p className="upload-error" role="alert">{error}</p>}

        <p className="upload-disclaimer">
          Interactive frontend demo only. No file is sent to a server,
          and no real video analysis is performed.
        </p>

        <p className="upload-tagline">
          Track every throw. Improve every catch.
        </p>
      </main>
    </div>
  );
}
