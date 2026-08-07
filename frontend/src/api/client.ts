import type {
  ClipInfo,
  ClipList,
  ClipSearchStatus,
  DevicesResponse,
  Health,
  HistoryList,
  LocateResult,
  TaskInfo,
} from "./types";

const API_BASE_KEY = "la_api_base";

/** Accept only an http(s) origin/URL; reject anything else (e.g. javascript:). */
function sanitizeBase(value: string | null): string {
  const cleaned = (value ?? "").trim().replace(/\/+$/, "");
  if (!cleaned) return "";
  try {
    const url = new URL(cleaned);
    if (url.protocol === "http:" || url.protocol === "https:") return cleaned;
  } catch {
    /* not a valid absolute URL */
  }
  return "";
}

/**
 * Base URL of the backend. Empty string = same origin (the nginx-served
 * production build, or the Vite dev proxy). Configurable at runtime so a user
 * can point the UI at a backend running on a remote GPU box. Validated to an
 * http(s) URL so a stored value can never become a script-bearing URL.
 */
export function getApiBase(): string {
  return sanitizeBase(localStorage.getItem(API_BASE_KEY));
}

export function setApiBase(base: string): void {
  const cleaned = sanitizeBase(base);
  if (cleaned) localStorage.setItem(API_BASE_KEY, cleaned);
  else localStorage.removeItem(API_BASE_KEY);
}

/**
 * Resolve a backend-relative path (e.g. an image_url) to a full URL.
 *
 * Always yields either a same-origin relative path or an `http(s)` absolute URL
 * (built and re-serialized via the URL API, with an explicit protocol allowlist),
 * so a stored backend base can never produce a script-bearing scheme at an
 * `<img src>` / `fetch` sink — even though `getApiBase()` already sanitizes it.
 */
export function resolveUrl(path: string): string {
  const rel = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBase();
  if (!base) return rel; // same origin
  const url = new URL(rel, base);
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : rel;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(resolveUrl(path), init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/api/health"),
  tasks: () => req<TaskInfo[]>("/api/tasks"),
  devices: () => req<DevicesResponse>("/api/devices"),
  setDevice: (index: number) =>
    req<DevicesResponse>("/api/device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    }),
  history: (limit = 50, offset = 0) =>
    req<HistoryList>(`/api/history?limit=${limit}&offset=${offset}`),
  historyItem: (id: string) => req<LocateResult>(`/api/history/${id}`),
  deleteHistory: (id: string) =>
    req<{ deleted: string }>(`/api/history/${id}`, { method: "DELETE" }),
  locate: (form: FormData) =>
    req<LocateResult>("/api/locate", { method: "POST", body: form }),
  uploadClip: (form: FormData) => req<ClipInfo>("/api/clips", { method: "POST", body: form }),
  listClips: (limit = 50, offset = 0) =>
    req<ClipList>(`/api/clips?limit=${limit}&offset=${offset}`),
  getClip: (id: string) => req<ClipInfo>(`/api/clips/${id}`),
  deleteClip: (id: string) => req<{ deleted: string }>(`/api/clips/${id}`, { method: "DELETE" }),
  startClipSearch: (clipId: string, form: FormData) =>
    req<ClipSearchStatus>(`/api/clips/${clipId}/search`, { method: "POST", body: form }),
  getClipSearch: (clipId: string, searchId: string) =>
    req<ClipSearchStatus>(`/api/clips/${clipId}/searches/${searchId}`),
  cancelClipSearch: (clipId: string, searchId: string) =>
    req<{ cancelling: string }>(`/api/clips/${clipId}/searches/${searchId}/cancel`, {
      method: "POST",
    }),
};
