import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { apiClient } from "../../../services/apiClient.ts";
import { createSession, startAnalysis } from "../../sessions/api.ts";
import { useAnalysisJob } from "../../sessions/hooks/useAnalysisJob.ts";
import { uploadVideo } from "../api.ts";
import type { CameraPerspective } from "../types.ts";
import "./UploadPage.css";

interface Dog { dog_id: string; name: string; breed: string; date_of_birth: string }

export default function LiveUploadPage() {
  const [dogs, setDogs] = useState<Dog[]>([]);
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
  const [jobId, setJobId] = useState<string | null>(null);
  const [addingDog, setAddingDog] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const dogController = useRef<AbortController | null>(null);
  const { job, error: jobError, isPolling } = useAnalysisJob(jobId);
  const busy = uploading || isPolling || addingDog;

  useEffect(() => {
    const abort = new AbortController();
    void apiClient.request<{ items: Dog[] }>("GET", "/dogs", { signal: abort.signal }).then(data => {
      if (!abort.signal.aborted) { setDogs(data.items); setDogId(data.items[0]?.dog_id ?? ""); }
    }).catch(error => { if (!abort.signal.aborted) setError(error.message); });
    return () => { abort.abort(); controller.current?.abort(); dogController.current?.abort(); };
  }, []);

  async function start() {
    const selections: Array<{ file: File; camera_perspective: CameraPerspective }> = mode === "sample_pair"
      ? front && side ? [{ file: front, camera_perspective: "front" }, { file: side, camera_perspective: "side" }] : []
      : single ? [{ file: single, camera_perspective: perspective }] : [];
    if (!dogId || selections.length === 0 || busy || controller.current) return;
    const abort = new AbortController(); controller.current = abort;
    setUploading(true); setError(""); setJobId(null); setSessionId(null);
    try {
      setStage("Creating session");
      const session = await createSession({ dog_id: dogId }, abort.signal);
      abort.signal.throwIfAborted();
      setSessionId(session.session_id);
      const ids: string[] = [];
      for (const input of selections) {
        setStage(`Uploading ${input.camera_perspective} video`);
        const value = await uploadVideo(session.session_id, input, abort.signal);
        ids.push(value.video_id);
      }
      setStage("Submitting analysis");
      const accepted = await startAnalysis(session.session_id, { mode, video_ids: ids }, abort.signal);
      if (!abort.signal.aborted) setJobId(accepted.job_id);
    } catch (error) {
      if (!abort.signal.aborted) setError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!abort.signal.aborted) setUploading(false);
      if (controller.current === abort) controller.current = null;
    }
  }

  const ready = dogId && (mode === "sample_pair" ? front && side : single);
  return <section className="upload-page"><h1>Upload video</h1><p>Local API mode · fixed-camera videos only. Outcomes remain candidates.</p>
    <div className="upload-card">
      <fieldset disabled={busy} style={{ border: 0 }}>
        <p><label>Dog <select value={dogId} onChange={e => setDogId(e.target.value)}>{dogs.map(d => <option key={d.dog_id} value={d.dog_id}>{d.name} · {d.breed}</option>)}</select></label></p>
        <p><label>Analysis mode <select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="single_view">Single fixed view</option><option value="sample_pair">Matching supplied sample pair</option></select></label></p>
        {mode === "single_view" ? <>
          <p><label>Perspective <select value={perspective} onChange={e => setPerspective(e.target.value as CameraPerspective)}><option value="front">Front</option><option value="side">Side</option></select></label></p>
          <label>Video <input type="file" accept="video/*,.mkv,.mov,.avi,.webm" onChange={e => setSingle(e.target.files?.[0] ?? null)} /></label>
        </> : <><p>Pair mode accepts the original matching front/side samples only. Unrelated recordings will be rejected.</p>
          <p><label>Front video <input type="file" accept="video/*" onChange={e => setFront(e.target.files?.[0] ?? null)} /></label></p>
          <p><label>Side video <input type="file" accept="video/*" onChange={e => setSide(e.target.files?.[0] ?? null)} /></label></p></>}
      </fieldset>
      {busy && <p role="status">{uploading ? stage : `${job?.stage ?? "Waiting for analysis"} · ${job?.status ?? "queued"}`} · {job?.progress_percent == null ? "Progress not measured" : `${job.progress_percent}%`}</p>}
      {job?.status === "completed" && <p role="status">Analysis complete. Results are saved.</p>}
      {(error || jobError || job?.error) && <p role="alert">{error || jobError?.message || job?.error?.message}</p>}
      <div className="upload-footer"><button className="upload-button upload-button-primary" type="button" disabled={!ready || busy} onClick={() => void start()}>Upload and analyze</button>
        {busy && <button type="button" onClick={() => { controller.current?.abort(); setUploading(false); setJobId(null); setError("Stopped waiting. An accepted server job may still be running; review the saved session."); }}>Stop waiting</button>}
        {sessionId && <Link to={`/sessions/${encodeURIComponent(sessionId)}`}>Review saved session</Link>}</div>
    </div>
    <details><summary>Add a dog to the local database</summary><form onSubmit={async event => {
      event.preventDefault(); if (addingDog || busy) return;
      const form = new FormData(event.currentTarget);
      const abort = new AbortController(); dogController.current = abort;
      setAddingDog(true); setError("");
      try {
        const dog = await apiClient.request<Dog>("POST", "/dogs", { json: { name: form.get("name"), breed: form.get("breed"), date_of_birth: form.get("date_of_birth") }, signal: abort.signal });
        if (!abort.signal.aborted) { setDogs(previous => [...previous, dog]); setDogId(dog.dog_id); }
      } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : String(error)); }
      finally { if (!abort.signal.aborted) setAddingDog(false); }
    }}><p><label>Name <input name="name" required maxLength={255} /></label></p><p><label>Breed <input name="breed" required maxLength={255} /></label></p><p><label>Date of birth <input name="date_of_birth" type="date" required /></label></p><button disabled={addingDog || busy}>Save dog</button></form></details>
  </section>;
}
