import { useEffect, useState } from "react";
import { getSession, listSessions } from "../api.ts";
import type { SessionDetail, SessionSummary } from "../types.ts";

export function useSessionHistory() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const items: SessionSummary[] = [];
      for (let page = 1; ; page++) {
        const result = await listSessions({ page, pageSize: 100, signal: controller.signal });
        items.push(...result.items);
        if (items.length >= result.total) break;
        if (result.items.length === 0) throw new Error("Incomplete session history returned by server.");
      }
      if (!controller.signal.aborted) setSessions(items);
    })().catch(error => {
      if (!controller.signal.aborted) setError(error);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);
  return { sessions, error, loading };
}

export function useSessionDetail(sessionId: string | undefined, revision: string | undefined) {
  const [state, setState] = useState<{ id?: string; value: SessionDetail | null; error: Error | null }>({ value: null, error: null });
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    void getSession(sessionId, controller.signal).then(value => {
      if (!controller.signal.aborted) setState({ id: sessionId, value, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ id: sessionId, value: null, error });
    });
    return () => controller.abort();
  }, [sessionId, revision]);
  return state.id === sessionId ? state : { value: null, error: null };
}
