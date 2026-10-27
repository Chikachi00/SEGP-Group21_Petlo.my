import { isActiveJob } from "../jobLifecycle.ts";
import { useEffect, useState } from "react";
import { getSession } from "../api.ts";
import { loadSessionHistory } from "../sessionHistory.ts";
import { waitUntilVisible } from "../../../services/browserVisibility.ts";
import type { SessionDetail, SessionSummary } from "../types.ts";

export function useSessionHistory({ trash = false }: { trash?: boolean } = {}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError(null); setRefreshing(true);
    void (async () => {
      await waitUntilVisible(controller.signal);
      const items = await loadSessionHistory({ trash, signal: controller.signal });
      if (!controller.signal.aborted) {
        setSessions(items);
        if (items.some(session => isActiveJob(session.status))) timer = setTimeout(() => setRevision(value => value + 1), 5000);
      }
    })().catch(error => { if (!controller.signal.aborted) setError(error); })
      .finally(() => { if (!controller.signal.aborted) { setLoading(false); setRefreshing(false); } });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [revision, trash]);
  return { sessions, error, loading, refreshing, refresh: () => setRevision(value => value + 1) };
}

export function useSessionDetail(sessionId: string | undefined, revision: string | undefined) {
  const [state, setState] = useState<{ id?: string; value: SessionDetail | null; error: Error | null }>({ value: null, error: null });
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    void getSession(sessionId, controller.signal).then(value => {
      if (!controller.signal.aborted) setState({ id: sessionId, value, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setState(previous => ({ id: sessionId, value: previous.id === sessionId ? previous.value : null, error }));
    });
    return () => controller.abort();
  }, [sessionId, revision]);
  return state.id === sessionId ? state : { value: null, error: null };
}
