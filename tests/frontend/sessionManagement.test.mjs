import test from "node:test";
import assert from "node:assert/strict";
import { pollAnalysisJob } from "../../src/features/sessions/analysisPolling.ts";
import { defaultSessionName, isActiveJob, isTerminalJob } from "../../src/features/sessions/jobLifecycle.ts";

test("paused/pausing/cancelling are active and cancelled is terminal", () => {
  for (const state of ["queued", "running", "pausing", "paused", "cancelling"]) {
    assert.equal(isActiveJob(state), true);
    assert.equal(isTerminalJob(state), false);
  }
  for (const state of ["completed", "failed", "cancelled"]) {
    assert.equal(isActiveJob(state), false);
    assert.equal(isTerminalJob(state), true);
  }
  assert.equal(defaultSessionName({ name: "My training", date: "2026-10-21T00:00:00Z" }), "My training");
  assert.ok(!defaultSessionName({ date: "2026-10-21T00:00:00Z" }).includes("undefined"));
});

test("polling keeps observing a paused task, resumes the same identity and stops on cancellation", async () => {
  const states = ["running", "pausing", "paused", "paused", "running", "cancelling", "cancelled"];
  let calls = 0;
  const updates = [];
  const result = await pollAnalysisJob("same-job", { signal: new AbortController().signal, intervalMs: 1,
    readJob: async () => ({ job_id: "same-job", status: states[calls++], error: null }),
    onUpdate: job => updates.push(job.status),
  });
  assert.equal(result.job_id, "same-job");
  assert.equal(result.status, "cancelled");
  assert.deepEqual(updates, states);
  assert.equal(calls, 7);
});
