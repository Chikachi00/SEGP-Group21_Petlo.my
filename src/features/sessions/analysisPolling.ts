import { ApiError } from "../../services/apiClient.ts";
import { getAnalysisJob } from "./api.ts";
import type { AnalysisJob } from "./types.ts";

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(signal.reason ?? new DOMException("Polling aborted", "AbortError"));
    };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** One request at a time. Abort stops observation; it does not cancel the server job. */
export async function pollAnalysisJob(jobId: string, options: {
  signal: AbortSignal;
  intervalMs?: number;
  maxWaitMs?: number;
  onUpdate?: (job: AnalysisJob) => void;
  readJob?: typeof getAnalysisJob;
}): Promise<AnalysisJob> {
  const { signal, intervalMs = 2000, maxWaitMs = 1_800_000, onUpdate, readJob = getAnalysisJob } = options;
  if (!Number.isFinite(intervalMs) || intervalMs <= 0 || !Number.isFinite(maxWaitMs) || maxWaitMs <= 0) {
    throw new Error("Polling intervals and time limits must be positive.");
  }
  const pollingSignal = AbortSignal.any([signal, AbortSignal.timeout(maxWaitMs)]);
  try {
    while (true) {
      pollingSignal.throwIfAborted();
      const job = await readJob(jobId, pollingSignal);
      pollingSignal.throwIfAborted();
      onUpdate?.(job);
      if (job.status === "completed" || job.status === "failed") return job;
      await wait(intervalMs, pollingSignal);
    }
  } catch (error) {
    if (!signal.aborted && pollingSignal.aborted) {
      throw new ApiError("Stopped waiting for analysis. The server job may still be running.", null, "POLL_TIMEOUT");
    }
    throw error;
  }
}
