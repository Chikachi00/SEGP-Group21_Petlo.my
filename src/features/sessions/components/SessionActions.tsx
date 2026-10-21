import { useEffect, useId, useRef, useState } from "react";
import { renameSession, restoreSession, trashSession } from "../api.ts";
import type { SessionSummary } from "../types.ts";
import { defaultSessionName, isActiveJob } from "../jobLifecycle.ts";

export default function SessionActions({ session, onChange, onDeleted }: {
  session: SessionSummary; onChange: () => void; onDeleted?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const dialogId = useId();
  useEffect(() => () => controller.current?.abort(), []);
  async function act(action: "rename" | "delete" | "restore") {
    if (controller.current) return;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError("");
    try {
      if (action === "rename") await renameSession(session.session_id, name.trim(), abort.signal);
      else if (action === "delete") await trashSession(session.session_id, abort.signal);
      else await restoreSession(session.session_id, abort.signal);
      if (!abort.signal.aborted) {
        setEditing(false); setConfirmDelete(false); onChange();
        if (action === "delete") onDeleted?.();
      }
    } catch (error) {
      if (!abort.signal.aborted) setError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!abort.signal.aborted) setBusy(false);
      if (controller.current === abort) controller.current = null;
    }
  }
  return <div className="session-actions" aria-busy={busy}>
    {session.deleted_at ? <button disabled={busy} onClick={() => void act("restore")}>Restore</button> : <>
      {!editing && !confirmDelete && <><button disabled={busy} onClick={() => { setName(defaultSessionName(session)); setEditing(true); setError(""); }}>Rename</button>
        <button className="session-danger" disabled={busy} onClick={() => { setConfirmDelete(true); setError(""); }}>Delete</button></>}
      {editing && <form className="session-rename" onSubmit={event => { event.preventDefault(); if (name.trim()) void act("rename"); }}>
        <label>Session name<input autoFocus required maxLength={120} value={name} disabled={busy} onChange={event => setName(event.target.value)} /></label>
        <button disabled={busy || !name.trim()} type="submit">Save name</button><button type="button" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
      </form>}
      {confirmDelete && <div className="session-confirm" role="dialog" aria-labelledby={dialogId}>
        <strong id={dialogId}>Move “{defaultSessionName(session)}” to Trash?</strong>
        <p>{isActiveJob(session.status) ? "Its analysis will be stopped. " : ""}The record, source files and saved outputs are retained so you can restore it.</p>
        <button className="session-danger" disabled={busy} onClick={() => void act("delete")}>Move to Trash</button>
        <button disabled={busy} onClick={() => setConfirmDelete(false)}>Keep session</button>
      </div>}
    </>}
    {busy && <span role="status">Saving…</span>}
    {error && <p className="analysis-error" role="alert">{error}</p>}
  </div>;
}
