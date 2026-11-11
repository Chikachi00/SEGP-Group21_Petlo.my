import { useEffect, useState } from "react";
import { pollAnalysisJob } from "../analysisPolling.ts";
import type { AnalysisJob } from "../types.ts";

/** Observes a saved job. Reconnecting never repeats upload or analysis-start requests. */
export function useAnalysisJob(requestedJobId: string | null, options: { intervalMs?: number; maxWaitMs?: number } = {}) {
  const jobId = requestedJobId?.trim() ? requestedJobId : null;
  const { intervalMs = 2000, maxWaitMs = 7_200_000 } = options;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    key: string | null; job: AnalysisJob | null; error: Error | null; isPolling: boolean; lastCheckedAt: number | null;
  }>({ key: null, job: null, error: null, isPolling: false, lastCheckedAt: null });
  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    setState(previous => ({ key: jobId, job: previous.key === jobId ? previous.job : null, error: null,
      isPolling: true, lastCheckedAt: previous.key === jobId ? previous.lastCheckedAt : null }));
    void pollAnalysisJob(jobId, {
      signal: controller.signal, intervalMs, maxWaitMs,
      onUpdate: job => {
        if (!controller.signal.aborted) setState({ key: jobId, job, error: null, isPolling: true, lastCheckedAt: Date.now() });
      },
    }).then(job => {
      if (!controller.signal.aborted) setState({ key: jobId, job, error: null, isPolling: false, lastCheckedAt: Date.now() });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState(previous => ({ ...previous, key: jobId,
        error: error instanceof Error ? error : new Error(String(error)), isPolling: false }));
    });
    return () => controller.abort();
  }, [jobId, intervalMs, maxWaitMs, attempt]);
  const current = jobId !== null && state.key === jobId;
  return {
    job: current ? state.job : null, error: current ? state.error : null,
    lastCheckedAt: current ? state.lastCheckedAt : null,
    isPolling: jobId !== null && (current ? state.isPolling : true),
    resume: () => setAttempt(value => value + 1),
  };
}
