export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export type ProjectStatus =
  | "CREATED"
  | "UPLOADED"
  | "PROCESSING"
  | "OCR_COMPLETE"
  | "AWAITING_REVIEW"
  | "ANALYZING"
  | "SCRIPT_GENERATED"
  | "VISUALIZING"
  | "NARRATION_GENERATED"
  | "RENDERING"
  | "COMPLETED"
  | "FAILED";

export interface MathExpression {
  id: string;
  element_type: string;
  original_text: string;
  latex?: string | null;
  bbox?: { x: number; y: number; width: number; height: number } | null;
  confidence: number;
  needs_review: boolean;
  user_corrected: boolean;
  order_index: number;
}

export interface Scene {
  id: string;
  scene_id: string;
  order_index: number;
  scene_type: string;
  title: string;
  narration: string;
  duration_target: number;
  duration_actual?: number | null;
  visualization_spec: Record<string, unknown>;
  status: string;
  error_message?: string | null;
}

export interface ProjectSummary {
  id: string;
  title: string;
  status: ProjectStatus;
  progress_percent: number;
  progress_stage?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  has_video: boolean;
  thumbnail_url?: string | null;
}

export interface ProjectDetail {
  id: string;
  title: string;
  status: ProjectStatus;
  progress_percent: number;
  progress_stage?: string | null;
  error_message?: string | null;
  voice_gender: string;
  voice_speed: number;
  language: string;
  accent: string;
  enable_subtitles: boolean;
  created_at: string;
  updated_at: string;
  uploaded_page_url?: string | null;
  expressions: MathExpression[];
  lesson_plan?: {
    topic: string;
    learning_objectives: string[];
    concepts: string[];
    prerequisites: string[];
    sections: Array<{ title: string; duration: number }>;
    teaching_sequence: string[];
    visualization_candidates: unknown[];
  } | null;
  script?: { full_script: string; segments: unknown[] } | null;
  scenes: Scene[];
  jobs: Array<{
    id: string;
    stage: string;
    status: string;
    progress_percent: number;
    message?: string | null;
    error_message?: string | null;
  }>;
  videos: Array<{
    id: string;
    resolution: string;
    duration_sec: number;
    url?: string | null;
    is_primary: boolean;
    validated: boolean;
  }>;
  subtitles: Array<{ id: string; format: string; url?: string | null }>;
  ocr_reviewed: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new Error(
      `Cannot reach the API at ${API_URL}. Start Docker services: docker compose up -d postgres redis minio minio-init api worker`
    );
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const api = {
  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (body: Partial<ProjectDetail> & { title?: string }) =>
    request<ProjectDetail>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getProject: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  updateProject: (id: string, body: Record<string, unknown>) =>
    request<ProjectDetail>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteProject: (id: string) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  upload: async (
    id: string,
    file: File,
    opts: { rotation?: number; page_number?: number; crop?: object | null }
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("rotation", String(opts.rotation ?? 0));
    form.append("page_number", String(opts.page_number ?? 1));
    if (opts.crop) form.append("crop_json", JSON.stringify(opts.crop));
    return request<ProjectDetail>(`/api/upload/${id}`, { method: "POST", body: form });
  },
  startOcr: (id: string) =>
    request<ProjectDetail>(`/api/ocr/${id}`, { method: "POST" }),
  updateExpression: (projectId: string, exprId: string, body: Record<string, unknown>) =>
    request(`/api/ocr/${projectId}/expressions/${exprId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  approveReview: (id: string, expressions?: unknown[]) =>
    request<ProjectDetail>(`/api/ocr/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ expressions: expressions || [] }),
    }),
  generate: (id: string, body: Record<string, unknown> = {}) =>
    request<ProjectDetail>(`/api/projects/${id}/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  videoDownloadUrl: (id: string, resolution = "1080p") =>
    `${API_URL}/api/video/${id}/download?resolution=${resolution}`,
  subtitleUrl: (id: string, fmt: "srt" | "vtt") =>
    `${API_URL}/api/video/${id}/subtitles/${fmt}`,
  lessonUrl: (id: string) => `${API_URL}/api/video/${id}/lesson`,
  progressUrl: (id: string) => `${API_URL}/api/progress/${id}`,
};
