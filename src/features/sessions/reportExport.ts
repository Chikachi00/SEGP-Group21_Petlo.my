import type { SessionDetail } from "./types.ts";

/** A machine candidate report, never an accuracy evaluation or a human annotation file. */
export function reportJson(session: SessionDetail): string {
  return JSON.stringify({ report_type: "unverified_candidate_report", exported_at: new Date().toISOString(), ...session }, null, 2);
}

export function reportCsv(session: SessionDetail): string {
  const cell = (value: string | number | boolean) => {
    const text = String(value);
    // Spreadsheet applications must not interpret identifiers as formulas.
    const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const header = ["session_id", "event_id", "candidate_category", "conflicting_views", "video_id", "camera_view", "start_seconds", "end_seconds", "human_verified"];
  const rows = session.events.flatMap(event => event.source_intervals.map(interval => [
    session.session_id, event.event_id, event.category, event.conflict, interval.video_id,
    session.videos.find(video => video.video_id === interval.video_id)?.camera_perspective ?? "unknown",
    interval.start_sec, interval.end_sec, false,
  ]));
  return [header, ...rows].map(row => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

export function downloadReport(session: SessionDetail, format: "json" | "csv") {
  const blob = new Blob([format === "json" ? reportJson(session) : "\uFEFF" + reportCsv(session)], { type: format === "json" ? "application/json" : "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = `petlo-${session.session_id}.${format}`;
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
