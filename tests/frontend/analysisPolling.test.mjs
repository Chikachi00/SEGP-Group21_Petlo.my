import test from "node:test";
import assert from "node:assert/strict";
import { pollAnalysisJob } from "../../src/features/sessions/analysisPolling.ts";

const job = status => ({ job_id: "job-1", session_id: "session-1", status, progress_percent: null, stage: null,
  error: status === "failed" ? { code: "ANALYSIS_FAILED", message: "Failed." } : null });

test("polling is sequential and stops on completion", async () => {
  let active = 0, maxActive = 0, calls = 0;
  const updates = [];
  const result = await pollAnalysisJob("job-1", {
    signal: new AbortController().signal, intervalMs: 1,
    readJob: async () => {
      maxActive = Math.max(maxActive, ++active);
      await new Promise(resolve => setTimeout(resolve, 3));
      active--;
      return job(++calls === 3 ? "completed" : "running");
    },
    onUpdate: value => updates.push(value.status),
  });
  assert.equal(result.status, "completed");
  assert.equal(calls, 3);
  assert.equal(maxActive, 1);
  assert.deepEqual(updates, ["running", "running", "completed"]);
});

test("failed jobs are terminal business results, not successful completion", async () => {
  let calls = 0;
  const result = await pollAnalysisJob("job-1", { signal: new AbortController().signal,
    readJob: async () => { calls++; return job("failed"); } });
  assert.equal(result.status, "failed");
  assert.equal(result.error.code, "ANALYSIS_FAILED");
  assert.equal(calls, 1);
});

test("abort during polling delay prevents a later request", async () => {
  const controller = new AbortController();
  let calls = 0;
  const polling = pollAnalysisJob("job-1", { signal: controller.signal, intervalMs: 1000,
    readJob: async () => { calls++; return job("running"); },
    onUpdate: () => queueMicrotask(() => controller.abort()),
  });
  await assert.rejects(polling, { name: "AbortError" });
  assert.equal(calls, 1);
});

test("request failures stop polling rather than repeatedly querying a broken API", async () => {
  let calls = 0;
  await assert.rejects(pollAnalysisJob("job-1", { signal: new AbortController().signal,
    readJob: async () => { calls++; throw new Error("offline"); } }), /offline/);
  assert.equal(calls, 1);
});

test("waiting deadline aborts an in-flight status request", async () => {
  // Keep the test event loop alive because AbortSignal.timeout timers are unreferenced in Node.
  const keepAlive = setTimeout(() => {}, 1000);
  try {
    await assert.rejects(pollAnalysisJob("job-1", { signal: new AbortController().signal, maxWaitMs: 10,
      readJob: async (_id, signal) => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      }) }), { code: "POLL_TIMEOUT" });
  } finally { clearTimeout(keepAlive); }
});

test("hidden tabs suspend status requests and resume the same job when visible", async () => {
  const previousDocument = globalThis.document;
  const visibility = new EventTarget();
  visibility.visibilityState = "hidden";
  globalThis.document = visibility;
  let calls = 0;
  try {
    const polling = pollAnalysisJob("job-1", { signal: new AbortController().signal,
      readJob: async id => { assert.equal(id, "job-1"); calls++; return job("completed"); },
    });
    await Promise.resolve();
    assert.equal(calls, 0);
    visibility.visibilityState = "visible";
    visibility.dispatchEvent(new Event("visibilitychange"));
    assert.equal((await polling).status, "completed");
    assert.equal(calls, 1);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
