/**
 * src/lib/cvm/scans.ts
 * --------------------
 * Running an assessment, and the history of ones already run.
 *
 * These are the write actions with CLI parity: `POST /scans` mirrors
 * `caspar scan CONFIG [--live]`, and `POST /scans/upload` exists because a
 * browser holds a File, not a server-side path.
 *
 * UNLIKE BUILDS, THESE ARE SYNCHRONOUS. A scan takes seconds, so it answers
 * with the result rather than a job id. Only the LLM-bound operations
 * (builds, installs) needed the job runner — see `jobs.ts`.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  apiDelete,
  apiGet,
  apiGetPaged,
  apiPost,
  apiPostForm,
  type Paged,
} from "./client";
import type { Severity } from "./types";

export type EnvProfile = "production" | "internal" | "dev";

export interface RunScanParams {
  input_path: string;
  live?: boolean;
  version?: string;
  env_profile?: EnvProfile;
  host?: string;
  threshold?: number;
  suppress_file?: string;
  assess_unknown?: boolean;
  docs_path?: string;
}

export interface UploadScanParams {
  file: File;
  env_profile?: EnvProfile;
  host?: string;
  threshold?: number;
}

/** What `POST /scans` answers with — ScanResult plus the CI-gating fields. */
export interface ScanResponse {
  scan_id: string;
  target_name: string;
  input_path: string;
  timestamp: string;
  global_temporal_score: number;
  severity: Severity;
  total_directives_scanned: number;
  total_issues_found: number;
  total_chains_detected: number;
  detected_version: string | null;
  // `caspar scan --threshold` decides an exit code; over HTTP that cannot be a
  // status (the scan itself succeeded), so it comes back as data.
  passed_threshold: boolean;
  suppressed_count: number;
}

/**
 * A row in the scan list.
 *
 * NOTE the field names differ from `ScanResponse`: the list endpoint reports
 * `total_issues`, the scan endpoint `total_issues_found`. Verified against the
 * live API rather than assumed — they are two serialisers, not one.
 */
export interface ScanListItem {
  id: string;
  target_name: string;
  input_path: string;
  timestamp: string;
  global_base_score: number;
  global_temporal_score: number;
  severity: Severity;
  total_directives: number;
  total_issues: number;
  total_chains: number;
  host_id: number | null;
}

export interface ListScansParams {
  target?: string;
  input_path?: string;
  severity_min?: number;
  limit?: number;
  offset?: number;
}

export function useScanHistory(
  params: ListScansParams = {},
): UseQueryResult<ScanListItem[]> {
  return useQuery({
    queryKey: ["scans", params],
    queryFn: () => apiGet<ScanListItem[]>("/scans", { ...params }),
  });
}

/**
 * The same history, plus how many assessments exist in total.
 *
 * Separate from `useScanHistory` because only a paged view needs the count: a
 * caller that asks for "the last 5" and shows all of them would gain nothing
 * from a total, and reading the header on every call would make the two
 * queries' cache entries differ in shape for no reason.
 *
 * `placeholderData` keeps the current page on screen while the next one is
 * fetched, so paging does not blank the table between clicks.
 */
export function useScanHistoryPaged(
  params: ListScansParams = {},
): UseQueryResult<Paged<ScanListItem>> {
  return useQuery({
    queryKey: ["scans", "paged", params],
    queryFn: () => apiGetPaged<ScanListItem>("/scans", { ...params }),
    placeholderData: (previous) => previous,
  });
}

/**
 * What a completed scan invalidates.
 *
 * A new scan changes the posture, the findings, the chains and the trend all
 * at once — every read view in the console is stale the moment it lands.
 * Listing them here keeps that knowledge in one place rather than in each
 * mutation's onSuccess.
 */
function useInvalidateAfterScan(): () => void {
  const qc = useQueryClient();
  return () => {
    for (const key of [
      "scans",
      "posture",
      "dimension",
      "findings",
      "chains",
      "targets",
      "trends",
      "hosts",
    ]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

/** Server-path / --live mode — mirrors `caspar scan CONFIG [--live]`. */
export function useRunScan() {
  const invalidate = useInvalidateAfterScan();
  return useMutation({
    mutationFn: (params: RunScanParams) =>
      apiPost<ScanResponse>("/scans", params),
    onSuccess: invalidate,
  });
}

/**
 * Browser-upload mode.
 *
 * The file lives client-side, so it cannot be a server path the way
 * `RunScanParams.input_path` is. The endpoint stages it to disk and then runs
 * the identical scan path — the assessment logic is the same one the CLI runs.
 */
export function useUploadScan() {
  const invalidate = useInvalidateAfterScan();
  return useMutation({
    mutationFn: (params: UploadScanParams) => {
      const form = new FormData();
      form.append("file", params.file);
      if (params.env_profile) form.append("env_profile", params.env_profile);
      if (params.host) form.append("host", params.host);
      if (params.threshold !== undefined) {
        form.append("threshold", String(params.threshold));
      }
      return apiPostForm<ScanResponse>("/scans/upload", form);
    },
    onSuccess: invalidate,
  });
}

/**
 * Delete a stored assessment.
 *
 * Every scan is kept, so without this the database grows without bound and the
 * console offers no way to prune it. The same scan feeds the posture and the
 * trends, hence the full invalidation — otherwise the overview keeps counting a
 * scan that no longer exists.
 */
export function useDeleteScan() {
  const invalidate = useInvalidateAfterScan();
  return useMutation({
    mutationFn: (scanId: string) => apiDelete<void>(`/scans/${scanId}`),
    onSuccess: invalidate,
  });
}

/**
 * An entry in a diff.
 *
 * These are raw serialised misconfigurations, not the contract's `Finding`
 * shape: the diff engine compares stored scan JSON directly (see
 * reports/scan_features.py). Only the fields the comparison view reads are
 * declared — the objects carry more.
 */
export interface DiffIssue {
  directive: string;
  target_name: string;
  bad_value: string;
  temporal_score: number;
}

export interface ScanDiff {
  old_score: number;
  new_score: number;
  score_delta: number;
  resolved: DiffIssue[];
  new_issues: DiffIssue[];
  unchanged: DiffIssue[];
}

/**
 * `POST /scans/{old}/diff/{new}` — what changed between two assessments.
 *
 * Order is load-bearing: the first id is the OLDER side. Swapping them inverts
 * the sign of every change, so a comparison run backwards reports fixes as
 * regressions.
 */
export function useCompareScans() {
  return useMutation({
    mutationFn: ({ older, newer }: { older: string; newer: string }) =>
      apiPost<ScanDiff>(`/scans/${older}/diff/${newer}`),
  });
}
