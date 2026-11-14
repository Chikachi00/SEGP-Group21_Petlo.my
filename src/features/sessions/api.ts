import { isActiveJob, isTerminalJob } from "./jobLifecycle.ts";
import { ApiError, apiClient } from "../../services/apiClient.ts";
import type { AnalysisJob, CreateSessionRequest, SessionDetail, SessionList, SessionSummary, StartAnalysisRequest } from "./types.ts";

function id(value: string): string {
  if (!value.trim()) throw new Error("Resource ID is required.");
  return encodeURIComponent(value);
}

export function createSession(input: CreateSessionRequest, signal?: AbortSignal): Promise<SessionSummary> {
  if (!input.dog_id.trim()) throw new Error("dog_id is required.");
  return apiClient.request("POST", "/sessions", { json: input, signal });
}

export function listSessions(options: { page?: number; pageSize?: number; trash?: boolean; signal?: AbortSignal } = {}): Promise<SessionList> {
  const { page = 1, pageSize = 20, trash = false, signal } = options;
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    throw new Error("Use page >= 1 and pageSize from 1 to 100.");
  }
  return apiClient.request("GET", `/sessions?page=${page}&page_size=${pageSize}${trash ? "&trash=true" : ""}`, { signal });
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
  return apiClient.request("GET", `/sessions/${id(sessionId)}`, { signal });
}

export function startAnalysis(sessionId: string, input: StartAnalysisRequest, signal?: AbortSignal): Promise<AnalysisJob> {
  const expectedCount = input.mode === "single_view" ? 1 : 2;
  if (!["single_view", "sample_pair", "paired_views"].includes(input.mode) || input.video_ids.length !== expectedCount ||
      input.video_ids.some(value => !value.trim()) || new Set(input.video_ids).size !== expectedCount) {
    throw new Error("Choose one video for single_view or two distinct videos for sample_pair.");
  }
  return apiClient.request("POST", `/sessions/${id(sessionId)}/analysis`, { json: input, signal });
}

export async function getAnalysisJob(jobId: string, signal?: AbortSignal): Promise<AnalysisJob> {
  const job = await apiClient.request<AnalysisJob>("GET", `/jobs/${id(jobId)}`, { signal });
  if (!job || job.job_id !== jobId || (!isActiveJob(job.status) && !isTerminalJob(job.status)) ||
      (job.progress_percent !== null && (!Number.isFinite(job.progress_percent) || job.progress_percent < 0 || job.progress_percent > 100))) {
    throw new ApiError("Server returned an invalid analysis job.", 200, "INVALID_RESPONSE");
  }
  return job;
}

export function renameSession(sessionId: string, name: string, signal?: AbortSignal): Promise<SessionSummary> {
  if (!name.trim() || name.trim().length > 120) throw new Error("Use a session name of 1–120 characters.");
  return apiClient.request("PATCH", `/sessions/${id(sessionId)}`, { json: { name: name.trim() }, signal });
}

export function trashSession(sessionId: string, signal?: AbortSignal): Promise<SessionSummary> {
  return apiClient.request("DELETE", `/sessions/${id(sessionId)}`, { signal });
}

export function restoreSession(sessionId: string, signal?: AbortSignal): Promise<SessionSummary> {
  return apiClient.request("POST", `/sessions/${id(sessionId)}/restore`, { signal });
}

export function controlAnalysisJob(jobId: string, action: "pause" | "resume" | "cancel", signal?: AbortSignal): Promise<AnalysisJob> {
  return apiClient.request("POST", `/jobs/${id(jobId)}/control`, { json: { action }, signal });
}
