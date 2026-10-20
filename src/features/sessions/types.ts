import type { SessionVideo } from "../videos/types.ts";

export type JobStatus = "queued" | "running" | "completed" | "failed";
export type SessionStatus = "draft" | "ready" | JobStatus;
export type CandidateCategory = "in_air_catch_candidate" | "ground_pickup_candidate" | "miss_candidate" | "uncertain";

export interface CandidateStatistics {
  report_type: "unverified_candidate_statistics";
  total_throw_candidates: number;
  classified_candidate_events: number;
  uncertain_events: number;
  candidate_counts: Record<CandidateCategory, number>;
  candidate_coverage: number | null;
  in_air_catch_candidate_rate: number | null;
  retrieval_candidate_rate: number | null;
  denominator_definition: string;
  human_labels_used_for_statistics: false;
}

export interface SessionSummary {
  session_id: string;
  date: string;
  dog_id: string;
  status: SessionStatus;
  statistics: CandidateStatistics | null;
}

export interface SessionEvent {
  event_id: string;
  category: CandidateCategory;
  conflict: boolean;
  source_intervals: Array<{
    video_id: string;
    start_sec: number;
    end_sec: number;
  }>;
}

export interface SessionDetail extends SessionSummary {
  current_job_id?: string | null;
  videos: SessionVideo[];
  events: SessionEvent[];
  algorithm_version: string | null;
  limitations: string[];
}

export interface SessionList {
  items: SessionSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface CreateSessionRequest {
  dog_id: string;
  recorded_at?: string;
}

export interface StartAnalysisRequest {
  video_ids: string[];
  mode: "single_view" | "sample_pair";
}

export interface AnalysisJob {
  job_id: string;
  session_id: string;
  status: JobStatus;
  progress_percent: number | null;
  stage: string | null;
  error: { code: string; message: string } | null;
}
