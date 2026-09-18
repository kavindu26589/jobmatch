import type {
  HealthStatus,
  MatchResult,
  PdfPositionsResult,
  ResumeAnalysis,
  SearchResult,
  UploadResult,
} from "./types";

const KEY_STORAGE = "jobmatcher.api_key";

export function getApiKey(): string {
  try {
    return (localStorage.getItem(KEY_STORAGE) ?? "").trim();
  } catch {
    return "";
  }
}

export function setApiKey(key: string): void {
  try {
    if (key.trim()) localStorage.setItem(KEY_STORAGE, key.trim());
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable — key kept in memory only */
  }
}

async function parseError(resp: Response, data: unknown): Promise<Error> {
  let detail = `HTTP ${resp.status}`;
  if (data && typeof data === "object") {
    const d = (data as { detail?: unknown }).detail;
    if (typeof d === "string") detail = d;
    else if (Array.isArray(d)) {
      detail = d
        .map((e) => {
          const item = e as { msg?: string };
          return item.msg ? String(item.msg) : JSON.stringify(e);
        })
        .join("; ");
    }
  }
  const err = new Error(detail);
  err.name = `ApiError${resp.status}`;
  return err;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${key}`);
  const resp = await fetch(path, { ...init, headers });
  const data = await resp.json().catch(() => null);
  if (!resp.ok) throw await parseError(resp, data);
  return data as T;
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadResult>("/api/v1/upload", { method: "POST", body: form });
}

export interface ExportResult {
  blob: Blob;
  filename: string;
  notes: string[];
}

/** URL that streams the original uploaded file bytes (design preserved). */
export function originalFileUrl(uploadId: string): string {
  return `/api/v1/cv/${encodeURIComponent(uploadId)}/file`;
}

export async function exportCv(
  uploadId: string,
  text: string,
  asFormat?: string,
): Promise<ExportResult | null> {
  if (!uploadId) return null;
  const headers = new Headers({ "Content-Type": "application/json" });
  const key = getApiKey();
  if (key) headers.set("Authorization", `Bearer ${key}`);
  const resp = await fetch("/api/v1/cv/export", {
    method: "POST",
    headers,
    body: JSON.stringify({ upload_id: uploadId, text, as_format: asFormat }),
  });
  const ct = resp.headers.get("content-type") ?? "";
  if (!resp.ok) {
    const data = await resp.json().catch(() => null);
    throw await parseError(resp, data);
  }
  const blob = await resp.blob();
  if (blob.size === 0 || ct === "application/json") return null;
  const disposition = resp.headers.get("content-disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const notes = (resp.headers.get("x-patch-notes") ?? "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
  return { blob, filename: match ? match[1] : "resume", notes };
}

export function health(): Promise<HealthStatus> {
  return apiGet<HealthStatus>("/health");
}

export const api = {
  analyze(text: string): Promise<ResumeAnalysis> {
    return apiPost<ResumeAnalysis>("/api/v1/analyze", { resume_text: text });
  },
  search(body: {
    query: string;
    location: string;
    remote_only: boolean;
    limit: number;
  }): Promise<SearchResult> {
    return apiPost<SearchResult>("/api/v1/search", body);
  },
  match(body: {
    resume_text: string;
    query: string;
    location: string;
    remote_only: boolean;
    limit: number;
    llm_top_n: number;
    min_score: number;
    improve: boolean;
  }): Promise<MatchResult> {
    return apiPost<MatchResult>("/api/v1/match", body);
  },
  agent(body: {
    resume_text: string;
    query: string;
    location: string;
    question: string;
    limit: number;
    llm_top_n: number;
    min_score: number;
    improve: boolean;
  }): Promise<MatchResult> {
    return apiPost<MatchResult>("/api/v1/agent", body);
  },
  getPositions(uploadId: string): Promise<PdfPositionsResult> {
    return apiGet<PdfPositionsResult>(`/api/v1/cv/${encodeURIComponent(uploadId)}/positions`);
  },
};