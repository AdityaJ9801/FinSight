import type {
  AddDocumentsResult, AssistantResponse, Benchmarks, Chart, DetailedAnalysis, Finding, HealthScore, IndustryList, Instruction, Job,
  LlmStatus, Metric, QaResponse, ReviewItem, TaskRun, ValidationCheck,
} from "./types";

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(API_BASE + path, init);
  } catch {
    throw new ApiError(0, "Can't reach the FinSight API. Check that the API server is running on port 5000.");
  }
  const text = await resp.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!resp.ok) {
    const err = body && typeof body === "object" ? (body as { error?: unknown }).error : undefined;
    const msg = err ? String(err) : `Request failed (${resp.status})`;
    throw new ApiError(resp.status, msg);
  }
  return body as T;
}

const json = (payload: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload ?? {}),
});

/** Multipart upload. A 503 still carries a job id (the job exists but the queue is down), so
 * surface it on the error for the caller to navigate to. */
async function upload<T>(path: string, form: FormData): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(API_BASE + path, { method: "POST", body: form });
  } catch {
    throw new ApiError(0, "Can't reach the FinSight API. Check that the API server is running on port 5000.");
  }
  const body = await resp.json().catch(() => ({}));
  if (resp.ok) return body as T;
  if (resp.status === 503) {
    const err = new ApiError(503, `Saved, but the task queue is unavailable: ${body.error ?? ""}. Start Redis and the Celery worker.`);
    (err as ApiError & { jobId?: string }).jobId = body.job_id;
    throw err;
  }
  throw new ApiError(resp.status, body.error ?? `Upload failed (${resp.status})`);
}

export const reportUrl = (jobId: string, format: "html" | "docx" | "pdf") =>
  `${API_BASE}/jobs/${jobId}/report?format=${format}`;

export const api = {
  listJobs: () => request<Job[]>("/jobs"),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  deleteJob: (id: string) => request<{ status: string }>(`/jobs/${id}`, { method: "DELETE" }),
  createJob: (files: File[], fields: { goal: string; planTemplate: string; companyName: string; industry: string }) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("goal", fields.goal);
    form.append("plan_template", fields.planTemplate);
    if (fields.companyName) form.append("company_name", fields.companyName);
    if (fields.industry) form.append("industry", fields.industry);
    return upload<{ job_id: string; status: string }>("/jobs", form);
  },
  addDocuments: (id: string, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return upload<AddDocumentsResult>(`/jobs/${id}/documents`, form);
  },
  updateProfile: (id: string, profile: { company_name?: string; industry?: string }) =>
    request<Job>(`/jobs/${id}/profile`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) }),
  industries: () => request<IndustryList>("/benchmarks/industries"),
  benchmarks: (id: string, industry?: string) =>
    request<Benchmarks>(`/jobs/${id}/benchmarks${industry ? `?industry=${encodeURIComponent(industry)}` : ""}`),
  tasks: (id: string) => request<TaskRun[]>(`/jobs/${id}/tasks`),
  metrics: (id: string) => request<Metric[]>(`/jobs/${id}/metrics`),
  findings: (id: string) => request<Finding[]>(`/jobs/${id}/findings`),
  charts: (id: string) => request<Chart[]>(`/jobs/${id}/charts`),
  validation: (id: string) => request<ValidationCheck[]>(`/jobs/${id}/validation`),
  health: (id: string) => request<HealthScore>(`/jobs/${id}/health`),
  reportExists: async (id: string) => {
    const resp = await fetch(reportUrl(id, "html"), { method: "HEAD" }).catch(() => null);
    return !!resp && resp.ok;
  },
  instructions: (id: string) => request<Instruction[]>(`/jobs/${id}/instructions`),
  addInstruction: (id: string, content: string) => request<Instruction>(`/jobs/${id}/instructions`, json({ content })),
  assistant: (id: string, payload: { message?: string; chosen_agent?: string; action_note?: string; auto?: boolean }) =>
    request<AssistantResponse>(`/jobs/${id}/assistant`, json(payload)),
  qa: (jobId: string, question: string, history: { role: string; content: string }[]) =>
    request<QaResponse>("/qa", json({ job_id: jobId, question, history })),
  reviewItems: (jobId: string) => request<ReviewItem[]>(`/review/items?job_id=${encodeURIComponent(jobId)}`),
  resolveReview: (itemId: string, resolution: { note?: string; account_id?: string }) =>
    request<{ status: string; remaining_open: number }>(`/review/items/${itemId}/resolve`, json(resolution)),
  agents: () => request<{ name: string; stage: string; label: string; description: string }[]>("/agents"),
  detailedAnalysis: (id: string) => request<DetailedAnalysis>(`/jobs/${id}/analysis`),
  llmStatus: () => request<LlmStatus>("/llm/status"),
  saveLlm: (payload: Record<string, unknown>) => request<LlmStatus>("/llm/config", json(payload)),
};
