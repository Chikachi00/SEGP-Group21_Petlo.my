import { useEffect, useState } from "react";
import { pollAnalysisJob } from "../analysisPolling.ts";
import type { AnalysisJob } from "../types.ts";

/** Observes an existing job; never creates a session, uploads a file, or starts analysis. */
export function useAnalysisJob(requestedJobId: string | null, options: { intervalMs?: number; maxWaitMs?: number } = {}) {
  const jobId = requestedJobId?.trim() ? requestedJobId : null;
  const { intervalMs = 2000, maxWaitMs = 1_800_000 } = options;
  const [state, setState] = useState<{
    key: string | null;
    job: AnalysisJob | null;
    error: Error | null;
    isPolling: boolean;
  }>({ key: null, job: null, error: null, isPolling: false });

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    setState({ key: jobId, job: null, error: null, isPolling: true });
    void pollAnalysisJob(jobId, {
      signal: controller.signal, intervalMs, maxWaitMs,
      onUpdate: job => {
        if (!controller.signal.aborted) setState({ key: jobId, job, error: null, isPolling: true });
      },
    }).then(job => {
      if (!controller.signal.aborted) setState({ key: jobId, job, error: null, isPolling: false });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState(previous => ({
        ...previous, key: jobId, error: error instanceof Error ? error : new Error(String(error)), isPolling: false,
      }));
    });
    return () => controller.abort();
  }, [jobId, intervalMs, maxWaitMs]);

  const current = jobId !== null && state.key === jobId;
  return {
    job: current ? state.job : null,
    error: current ? state.error : null,
    isPolling: jobId !== null && (current ? state.isPolling : true),
  };
}
