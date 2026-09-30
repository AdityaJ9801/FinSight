import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { isActive, registerAgents } from "./pipeline";
import type { Job } from "./types";

const LIVE_MS = 1500;

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: api.listJobs,
    // Keep the sidebar/list fresh while anything is running.
    refetchInterval: (q) => (q.state.data?.some((j) => isActive(j.status)) ? 3000 : 20000),
  });
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId),
    refetchInterval: (q) => (q.state.error ? false : isActive(q.state.data?.status) ? LIVE_MS : false),
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  });
}

export function useTasks(jobId: string, job: Job | undefined) {
  return useQuery({
    queryKey: ["tasks", jobId],
    queryFn: () => api.tasks(jobId),
    enabled: !!job,
    refetchInterval: isActive(job?.status) ? LIVE_MS : false,
  });
}

export function useInstructions(jobId: string, job: Job | undefined) {
  return useQuery({
    queryKey: ["instructions", jobId],
    queryFn: () => api.instructions(jobId),
    enabled: !!job,
    refetchInterval: isActive(job?.status) ? 3000 : false,
  });
}

export function useReviewItems(jobId: string, job: Job | undefined) {
  return useQuery({
    queryKey: ["review", jobId],
    queryFn: () => api.reviewItems(jobId),
    enabled: job?.status === "AWAITING_REVIEW" || job?.status === "NEEDS_ANALYST",
  });
}

/** Results only exist once the data stage has produced a dataset version. */
export function useResults(jobId: string, job: Job | undefined) {
  const ready = !!job?.dataset_version_id;
  const metrics = useQuery({ queryKey: ["metrics", jobId], queryFn: () => api.metrics(jobId), enabled: ready });
  const findings = useQuery({ queryKey: ["findings", jobId], queryFn: () => api.findings(jobId), enabled: ready });
  const charts = useQuery({ queryKey: ["charts", jobId], queryFn: () => api.charts(jobId), enabled: ready });
  const validation = useQuery({ queryKey: ["validation", jobId], queryFn: () => api.validation(jobId), enabled: ready });
  const health = useQuery({ queryKey: ["health", jobId], queryFn: () => api.health(jobId), enabled: ready, retry: false });
  const report = useQuery({ queryKey: ["report", jobId], queryFn: () => api.reportExists(jobId), enabled: ready });
  return { metrics, findings, charts, validation, health, report };
}

/** When a job's status changes (e.g. finishes, or a re-run lands), refresh everything derived from it. */
export function useInvalidateOnStatusChange(jobId: string, job: Job | undefined) {
  const qc = useQueryClient();
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    const key = job ? `${job.status}:${job.dataset_version_id ?? ""}` : undefined;
    if (prev.current !== undefined && key !== prev.current) {
      refreshResults(qc, jobId);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    }
    prev.current = key;
  }, [job, jobId, qc]);
}

export function refreshResults(qc: ReturnType<typeof useQueryClient>, jobId: string) {
  for (const k of ["metrics", "findings", "charts", "validation", "health", "report", "tasks", "review", "instructions", "benchmarks", "analysis"]) {
    qc.invalidateQueries({ queryKey: [k, jobId] });
  }
}

export function useLlmStatus() {
  return useQuery({ queryKey: ["llm"], queryFn: api.llmStatus, staleTime: 30000, retry: 1 });
}

export function useAgentRegistry() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: async () => { const list = await api.agents(); registerAgents(list); return list; },
    staleTime: Infinity, retry: 1,
  });
}

export function useDetailedAnalysis(jobId: string, job: Job | undefined) {
  return useQuery({
    queryKey: ["analysis", jobId],
    queryFn: () => api.detailedAnalysis(jobId),
    enabled: !!job?.dataset_version_id,
    retry: false,
  });
}

export function useIndustries() {
  return useQuery({ queryKey: ["industries"], queryFn: api.industries, staleTime: Infinity });
}

export function useBenchmarks(jobId: string, job: Job | undefined, industry: string | null | undefined) {
  return useQuery({
    queryKey: ["benchmarks", jobId, industry ?? ""],
    queryFn: () => api.benchmarks(jobId, industry ?? undefined),
    enabled: !!job?.dataset_version_id && !!industry,
    retry: false,
  });
}
