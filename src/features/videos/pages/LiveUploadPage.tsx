import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { apiClient } from "../../../services/apiClient.ts";
import { createSession, startAnalysis } from "../../sessions/api.ts";
import { uploadVideo } from "../api.ts";
import type { CameraPerspective } from "../types.ts";
import "./UploadPage.css";
import "../../sessions/analysis.css";

interface Dog { dog_id: string; name: string; breed: string; date_of_birth: string }
interface Health { status: string; mode: string; max_upload_bytes: number }

export default function LiveUploadPage() {
  const navigate = useNavigate();
  const [dogs, setDogs] = useState<Dog[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [connecting, setConnecting] = useState(true);
  const [sessionName, setSessionName] = useState("");
  const [dogId, setDogId] = useState("");
  const [mode, setMode] = useState<"single_view" | "sample_pair">("single_view");
  const [perspective, setPerspective] = useState<CameraPerspective>("front");
  const [single, setSingle] = useState<File | null>(null);
  const [front, setFront] = useState<File | null>(null);
  const [side, setSide] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [stage, setStage] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [addingDog, setAddingDog] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const dogController = useRef<AbortController | null>(null);
  const busy = uploading || addingDog;

  useEffect(() => {
    const abort = new AbortController();
    setConnecting(true); setError(""); setHealth(null);
    void Promise.all([
      apiClient.request<Health>("GET", "/health", { signal: abort.signal }),
      apiClient.request<{ items: Dog[] }>("GET", "/dogs", { signal: abort.signal }),
    ]).then(([status, data]) => {
      if (!abort.signal.aborted) {
        if (status.status !== "ok" || !Number.isFinite(status.max_upload_bytes) || status.max_upload_bytes <= 0) throw new Error("Backend readiness could not be confirmed.");
        setHealth(status); setDogs(data.items); setDogId(previous => data.items.some(dog => dog.dog_id === previous) ? previous : data.items[0]?.dog_id ?? "");
      }
    }).catch(error => { if (!abort.signal.aborted) setError(error.message); })
      .finally(() => { if (!abort.signal.aborted) setConnecting(false); });
    return () => abort.abort();
  }, [loadAttempt]);
  useEffect(() => () => { controller.current?.abort(); dogController.current?.abort(); }, []);

  async function start() {
    const selections: Array<{ file: File; camera_perspective: CameraPerspective }> = mode === "sample_pair"
      ? front && side ? [{ file: front, camera_perspective: "front" }, { file: side, camera_perspective: "side" }] : []
      : single ? [{ file: single, camera_perspective: perspective }] : [];
    if (!health || !dogId || selections.length === 0 || busy || controller.current) return;
    for (const { file } of selections) {
      if (!/\.(mp4|mov|mkv|avi|webm)$/i.test(file.name) || file.size === 0) { setError("Choose a non-empty MP4, MOV, MKV, AVI or WebM video."); return; }
      if (file.size > health.max_upload_bytes) { setError(`${file.name} exceeds the local limit of ${Math.floor(health.max_upload_bytes / 1048576)} MiB per file.`); return; }
    }
    const abort = new AbortController(); controller.current = abort;
    setUploading(true); setError(""); setSessionId(null);
    try {
      setStage("Creating saved session…");
      const session = await createSession({ dog_id: dogId, name: sessionName.trim() || undefined }, abort.signal);
      abort.signal.throwIfAborted(); setSessionId(session.session_id);
      const ids: string[] = [];
      for (const input of selections) {
        setStage(`Uploading and validating ${input.camera_perspective} video…`);
        ids.push((await uploadVideo(session.session_id, input, abort.signal)).video_id);
      }
      setStage("Submitting background analysis…");
      await startAnalysis(session.session_id, { mode, video_ids: ids }, abort.signal);
      abort.signal.throwIfAborted();
      navigate(`/sessions/${encodeURIComponent(session.session_id)}/analysis`);
    } catch (error) {
      if (!abort.signal.aborted) setError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!abort.signal.aborted) setUploading(false);
      if (controller.current === abort) controller.current = null;
    }
  }

  const ready = Boolean(health && dogId && (mode === "sample_pair" ? front && side : single));
  return <section className="upload-page live-upload-form"><h1>Upload video</h1><p className="upload-subtitle">Choose a fixed-camera video. Follow the saved analysis task, then review its report.</p>
    <div className="upload-card">
      <p role="status">{connecting ? "Connecting to local backend…" : health ? `Backend connected · ${Math.floor(health.max_upload_bytes / 1048576)} MiB maximum per file` : "Backend unavailable. Start the local backend and retry."}</p>
      {!health && !connecting && <button onClick={() => setLoadAttempt(value => value + 1)}>Retry backend connection</button>}
      <fieldset disabled={busy || !health} style={{ border: 0 }}>
        <legend className="sr-only">Video analysis settings</legend>
        <p><label>Session name (optional)<input maxLength={120} value={sessionName} placeholder="e.g. Wednesday training — Front view" onChange={event => setSessionName(event.target.value)} /></label></p>
        <p><label>Dog <select value={dogId} onChange={e => setDogId(e.target.value)}>{dogs.map(d => <option key={d.dog_id} value={d.dog_id}>{d.name} · {d.breed}</option>)}</select></label></p>
        <p><label>Analysis mode <select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="single_view">Single fixed view</option><option value="sample_pair">Matching supplied sample pair</option></select></label></p>
        {mode === "single_view" ? <>
          <p><label>Perspective <select value={perspective} onChange={e => setPerspective(e.target.value as CameraPerspective)}><option value="front">Front</option><option value="side">Side</option></select></label></p>
          <label>Video <input type="file" accept="video/*,.mkv,.mov,.avi,.webm" onChange={e => setSingle(e.target.files?.[0] ?? null)} /></label>
          {single && <p className="analysis-muted">{single.name} · {(single.size / 1048576).toFixed(1)} MiB</p>}
        </> : <><p className="analysis-muted">Use the original matching front/side samples. Arbitrary video pairs are not supported yet.</p>
          <p><label>Front video <input type="file" accept="video/*" onChange={e => setFront(e.target.files?.[0] ?? null)} /></label></p>
          <p><label>Side video <input type="file" accept="video/*" onChange={e => setSide(e.target.files?.[0] ?? null)} /></label></p></>}
      </fieldset>
      {uploading && <div role="status"><p><span className="analysis-spinner" aria-hidden="true" /> {stage}</p><p className="analysis-muted">Keep this page open until upload is accepted. Byte progress is not measured.</p></div>}
      {error && <p className="analysis-error" role="alert">{error}</p>}
      <div className="upload-footer"><button className="upload-button upload-button-primary" type="button" disabled={!ready || busy} onClick={() => void start()}>Upload and analyze</button>
        {uploading && <button type="button" onClick={() => { controller.current?.abort(); setUploading(false); setError("Stopped waiting. A submitted task may still be running. Check the saved session before uploading again."); }}>Stop waiting</button>}
        {sessionId && <Link to={`/sessions/${encodeURIComponent(sessionId)}/analysis`}>Check saved session</Link>}</div>
    </div>
    <details className="analysis-card panel"><summary>Add a dog to the local database</summary><form onSubmit={async event => {
      event.preventDefault(); if (addingDog || busy || !health) return;
      const form = new FormData(event.currentTarget);
      const abort = new AbortController(); dogController.current = abort;
      setAddingDog(true); setError("");
      try {
        const dog = await apiClient.request<Dog>("POST", "/dogs", { json: { name: form.get("name"), breed: form.get("breed"), date_of_birth: form.get("date_of_birth") }, signal: abort.signal });
        if (!abort.signal.aborted) { setDogs(previous => [...previous, dog]); setDogId(dog.dog_id); }
      } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : String(error)); }
      finally { if (!abort.signal.aborted) setAddingDog(false); }
    }}><p><label>Name <input name="name" required maxLength={255} /></label></p><p><label>Breed <input name="breed" required maxLength={255} /></label></p><p><label>Date of birth <input name="date_of_birth" type="date" required /></label></p><button disabled={busy || !health}>Save dog</button></form></details>
    <p className="analysis-muted">Local single-user mode. Results are machine candidates, not human-verified outcomes.</p>
  </section>;
}
