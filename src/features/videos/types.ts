export type CameraPerspective = "front" | "side";

export interface SessionVideo {
  video_id: string;
  session_id: string;
  camera_perspective: CameraPerspective;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  playback_url: string | null;
  preview_url: string | null;
}

export interface UploadVideoRequest {
  file: File;
  camera_perspective: CameraPerspective;
}
