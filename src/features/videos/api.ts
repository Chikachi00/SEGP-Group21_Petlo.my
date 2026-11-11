import { apiClient } from "../../services/apiClient.ts";
import type { SessionVideo, UploadVideoRequest } from "./types.ts";

/** Resolves on upload acceptance, not on completion of algorithm analysis. */
export function uploadVideo(sessionId: string, input: UploadVideoRequest, signal?: AbortSignal): Promise<SessionVideo> {
  if (!sessionId.trim()) throw new Error("sessionId is required.");
  if (input.file.size === 0) throw new Error("Choose a non-empty video file.");
  if (input.camera_perspective !== "front" && input.camera_perspective !== "side") {
    throw new Error("Choose front or side camera perspective.");
  }
  const form = new FormData();
  form.append("file", input.file);
  form.append("camera_perspective", input.camera_perspective);
  return apiClient.request("POST", `/sessions/${encodeURIComponent(sessionId)}/videos`, {
    body: form, signal, timeoutMs: 600_000,
  });
}
