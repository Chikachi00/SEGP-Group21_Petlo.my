import test from "node:test";
import assert from "node:assert/strict";
import { analysisSteps, elapsedSeconds, formatElapsed, stageLabel } from "../../src/features/sessions/analysisPresentation.ts";
import { reportCsv, reportJson } from "../../src/features/sessions/reportExport.ts";

test("stage order follows the real paired pipeline and single-side mode excludes front/fusion", () => {
  const pair = analysisSteps(["side", "front"]).map(step => step.id);
  assert.ok(pair.indexOf("front:events") < pair.indexOf("side:preview"));
  assert.ok(pair.indexOf("side:events") < pair.indexOf("fusion"));
  assert.ok(pair.indexOf("fusion") < pair.indexOf("statistics"));
  const side = analysisSteps(["side"]).map(step => step.id);
  assert.ok(!side.some(id => id.startsWith("front:")));
  assert.ok(!side.includes("fusion"));
  assert.equal(stageLabel("side:disc_tracks"), "Side · Track and recover the disc");
  assert.equal(stageLabel("interrupted"), "Interrupted by a server restart");
});

test("elapsed time includes queuing but freezes at terminal completion and tolerates clock skew", () => {
  const start = "2026-10-21T00:00:00Z";
  assert.equal(elapsedSeconds({ status: "queued", created_at: start, finished_at: null }, Date.parse(start) + 91000), 91);
  assert.equal(elapsedSeconds({ status: "completed", created_at: start, finished_at: "2026-10-21T00:00:20Z" }, Date.parse(start) + 60000), 20);
  assert.equal(elapsedSeconds({ status: "running", created_at: start, finished_at: null }, Date.parse(start) - 1000), 0);
  assert.equal(elapsedSeconds({ status: "failed", created_at: start, finished_at: null }, Date.now()), null);
  assert.equal(elapsedSeconds(null, Date.now()), null);
  assert.equal(formatElapsed(3661), "1h 1m 1s");
});

const session = { session_id: "s1", status: "completed", statistics: { in_air_catch_candidate_rate: null }, videos: [
  { video_id: "front", camera_perspective: "front" }, { video_id: "side", camera_perspective: "side" },
], events: [{ event_id: '=unsafe,"id"', category: "ground_pickup_candidate", conflict: true,
  source_intervals: [{ video_id: "front", start_sec: 10, end_sec: 12 }, { video_id: "side", start_sec: 10.4, end_sec: 12.4 }] }] };

test("exports preserve per-view source times, null rates and unverified candidate provenance", () => {
  const json = JSON.parse(reportJson(session));
  assert.equal(json.statistics.in_air_catch_candidate_rate, null);
  assert.equal(json.report_type, "unverified_candidate_report");
  assert.deepEqual(json.events, session.events);
  const csv = reportCsv(session);
  assert.equal(csv.trim().split("\r\n").length, 3);
  assert.ok(csv.includes('"front","10","12","false"'));
  assert.ok(csv.includes('"side","10.4","12.4","false"'));
  assert.ok(csv.includes('"\'=unsafe,""id"""'));
  assert.equal(reportCsv({ ...session, events: [] }).trim().split("\r\n").length, 1);
});
