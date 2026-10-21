import { isTerminalJob } from "./jobLifecycle.ts";
import type { AnalysisJob } from "./types.ts";

const operations = [
  ["preview", "Create playback"], ["detect", "Detect dogs and discs"],
  ["dog_tracks", "Track the dog"], ["disc_tracks", "Track and recover the disc"],
  ["joint", "Analyze dog–disc interaction"], ["events", "Identify event candidates"],
] as const;

export function analysisSteps(views: string[]) {
  const ordered = ["front", "side"].filter(view => views.includes(view));
  return [
    { id: "queued", label: "Wait in queue" },
    { id: "prepare", label: "Decode and index source frames" },
    { id: "evidence_previews", label: "Prepare frame-aligned evidence" },
    ...ordered.flatMap(view => operations.map(([id, label]) => ({ id: `${view}:${id}`, label: `${view === "front" ? "Front" : "Side"} · ${label}` }))),
    ...(ordered.length === 2 ? [{ id: "fusion", label: "Combine the supplied sample views" }] : []),
    { id: "statistics", label: "Build report and save results" },
    { id: "complete", label: "Report ready" },
  ];
}

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "Checking task status";
  if (stage === "interrupted") return "Interrupted by a server restart";
  return analysisSteps(["front", "side"]).find(step => step.id === stage)?.label ?? stage.replaceAll("_", " ");
}

/** Submission time includes queueing; checking status is not a worker heartbeat. */
export function elapsedSeconds(job: Pick<AnalysisJob, "created_at" | "finished_at" | "status"> | null, nowMs: number): number | null {
  if (!job?.created_at) return null;
  const start = Date.parse(job.created_at);
  const terminal = isTerminalJob(job.status);
  if (terminal && !job.finished_at) return null;
  const end = terminal ? Date.parse(job.finished_at!) : nowMs;
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.floor((end - start) / 1000)) : null;
}

export function formatElapsed(seconds: number | null): string {
  if (seconds === null) return "Not recorded";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${hours ? `${hours}h ` : ""}${minutes}m ${Math.floor(seconds % 60)}s`;
}
