/**
 * src/lib/cvm/jobs.ts
 * -------------------
 * The background-job surface: builds, plugin installs, and the polling that
 * makes an hour-long operation watchable from a browser.
 *
 * WHY THESE ARE NOT `apiGet` HOOKS LIKE THE REST. Every other endpoint answers
 * a question about state that already exists. These START work and then report
 * on it, so the write returns a `job_id` at 202 and the reading is a poll that
 * has to know when to stop. That is a different lifecycle, and keeping it in
 * its own module says so.
 *
 * Ported from the v1 console (`frontend/src/api/jobs.ts`), which had this
 * working against the same endpoints; the polling design below is its work,
 * re-pointed at v2's client.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiGet, apiPost } from "./client";

/** The approved cadence for job polling (PLANO_V2 §Fase 2). */
const POLL_MS = 2000;

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  params_json: string;
  // Null until the job ends: a running job has produced no result and failed
  // with no error, and saying either would be a claim about an outcome that
  // has not happened.
  result_json: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobLogLine {
  seq: number;
  ts: string;
  line: string;
}

export interface InstalledPlugin {
  name: string;
  display_name: string;
  version: string;
  benchmark_source: string;
}

export interface AvailablePlugin {
  service: string;
  service_name: string;
  sources: { type: string | null; title: string; format: string }[];
}

export interface PluginsResponse {
  installed: InstalledPlugin[];
  available: AvailablePlugin[];
}

/** A job in a terminal state never changes again. */
export function isTerminal(status: JobStatus | undefined): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function useJobs(kind?: string): UseQueryResult<Job[]> {
  return useQuery({
    queryKey: ["jobs", kind ?? null],
    queryFn: () => apiGet<Job[]>("/jobs", { kind }),
  });
}

/**
 * One job, polled until it finishes.
 *
 * Polling stops at a terminal state rather than running forever: a finished
 * job cannot change, so continuing would be pure waste on a page someone may
 * leave open all afternoon.
 */
export function useJob(jobId: string | undefined): UseQueryResult<Job> {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => apiGet<Job>(`/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) =>
      isTerminal(query.state.data?.status) ? false : POLL_MS,
  });
}

/**
 * Tails a job's log.
 *
 * Lines accumulate client-side and the server is only ever asked for
 * `seq > last seen`, so a build that runs for an hour and forty minutes
 * (measured) does not re-ship its entire log every two seconds.
 */
export function useJobLogs(
  jobId: string | undefined,
  jobStatus: JobStatus | undefined,
): { lines: JobLogLine[]; isLoading: boolean } {
  const [lines, setLines] = useState<JobLogLine[]>([]);
  const afterRef = useRef(-1);

  // A new job means a fresh log — otherwise the previous job's output would
  // appear above this one's, reading as though it belonged to it.
  useEffect(() => {
    setLines([]);
    afterRef.current = -1;
  }, [jobId]);

  const query = useQuery({
    queryKey: ["job", jobId, "logs"],
    queryFn: async () => {
      const fresh = await apiGet<JobLogLine[]>(`/jobs/${jobId}/logs`, {
        after: afterRef.current,
      });
      if (fresh.length > 0) {
        afterRef.current = fresh[fresh.length - 1]!.seq;
        setLines((prev) => [...prev, ...fresh]);
      }
      return fresh;
    },
    enabled: Boolean(jobId),
    // One beat past terminal, so the final lines always land: the job's last
    // write can happen after the status flips.
    refetchInterval: isTerminal(jobStatus) ? false : POLL_MS,
  });

  return { lines, isLoading: query.isLoading };
}

export type BuildProvider = "ollama" | "anthropic" | "openai";

export interface StartBuildParams {
  benchmark: string;
  target?: "apache-httpd" | "nginx";
  model?: string;
  ollama_url?: string;
  dry_run?: boolean;
  provider?: BuildProvider;
}

/**
 * One engine a build can run on.
 *
 * NOTE WHAT IS ABSENT: the key itself. The server reads it from its own
 * environment and reports only whether the variable is set — a key that
 * reached the browser would be in the page, in the query cache, and in
 * anything that logs a response body.
 */
export interface BuildProviderInfo {
  id: BuildProvider;
  label: string;
  default_model: string;
  requires_key: boolean;
  /** The env var to export; "" for a provider that needs no key. */
  key_env: string;
  key_present: boolean;
}

export function useBuildProviders(): UseQueryResult<BuildProviderInfo[]> {
  return useQuery({
    queryKey: ["builds", "providers"],
    queryFn: () => apiGet<BuildProviderInfo[]>("/builds/providers"),
    // Exporting a key requires restarting the server anyway, so this changes
    // about as often as the process does.
    staleTime: 30_000,
  });
}

export function useStartBuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: StartBuildParams) =>
      apiPost<{ job_id: string }>("/builds", params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function usePlugins(): UseQueryResult<PluginsResponse> {
  return useQuery({
    queryKey: ["plugins"],
    queryFn: () => apiGet<PluginsResponse>("/plugins"),
  });
}

export interface InstallPluginParams {
  source: string;
  manual?: string;
  dry_run?: boolean;
  no_llm?: boolean;
  model?: string;
}

export function useInstallPlugin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: InstallPluginParams) =>
      apiPost<{ job_id: string }>("/plugins/install", params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

/**
 * What a finished build or install invalidates.
 *
 * A new plugin changes what can be assessed and what the knowledge base holds,
 * so the posture and target views are stale the moment a job succeeds — but
 * only then. Invalidating on every poll would refetch the whole console every
 * two seconds.
 */
export function useInvalidateAfterJob(): () => void {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["plugins"] });
    qc.invalidateQueries({ queryKey: ["targets"] });
    qc.invalidateQueries({ queryKey: ["knowledge"] });
    qc.invalidateQueries({ queryKey: ["posture"] });
  };
}
