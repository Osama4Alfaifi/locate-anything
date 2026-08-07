export type GenerationMode = "fast" | "hybrid" | "slow";

export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label?: string | null;
}

export interface Point {
  x: number;
  y: number;
  label?: string | null;
}

export interface TaskInfo {
  name: string;
  label: string;
  output_type: "box" | "point";
  input_kind: "categories" | "phrase" | "none";
  placeholder: string;
  description: string;
}

export type BackendStatus = "loading" | "ready" | "error";

export interface DeviceInfo {
  index: number;
  name: string;
  vram_gb: number | null;
  vram_free_gb: number | null;
  compatible: boolean;
}

export interface DevicesResponse {
  current: number | null;
  devices: DeviceInfo[];
}

export interface Health {
  status: BackendStatus;
  mock: boolean;
  model_loaded: boolean;
  model_path: string;
  device: string | null;
  device_index: number | null;
  gpu_name: string | null;
  vram_gb: number | null;
  compatible: boolean | null;
  note: string | null;
}

export interface LocateResult {
  id: string;
  task: string;
  prompt: string;
  generation_mode: GenerationMode;
  image_width: number;
  image_height: number;
  image_url: string;
  boxes: Box[];
  points: Point[];
  raw: string;
  stats: Record<string, unknown> | null;
  timing_ms: number;
  created_at: string;
}

export interface HistoryItem {
  id: string;
  task: string;
  prompt: string;
  generation_mode: GenerationMode;
  image_url: string;
  box_count: number;
  point_count: number;
  created_at: string;
}

export interface HistoryList {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export type ClipStatus = "extracting" | "ready" | "error";
export type SearchStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface ClipInfo {
  id: string;
  filename: string;
  status: ClipStatus;
  error: string | null;
  duration_s: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  sample_fps: number;
  frame_count: number;
  video_url: string;
  created_at: string;
}

export interface ClipList {
  items: ClipInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface ClipMatch {
  frame_id: string;
  frame_index: number;
  timestamp_ms: number;
  image_url: string;
  width: number;
  height: number;
  boxes: Box[];
  points: Point[];
  raw: string;
}

export interface ClipSearchStatus {
  id: string;
  clip_id: string;
  task: string;
  prompt: string;
  generation_mode: GenerationMode;
  status: SearchStatus;
  error: string | null;
  frames_total: number;
  frames_done: number;
  matches: ClipMatch[] | null;
  created_at: string;
  finished_at: string | null;
}

export interface ClipSearchList {
  items: ClipSearchStatus[];
}
