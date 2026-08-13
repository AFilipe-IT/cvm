/**
 * src/lib/cvm/manage.ts
 * ---------------------
 * The management surface: accepted risks, DB integrity, remediation previews
 * and the rule-promotion scoreboard.
 *
 * TWO ASYMMETRIES WITH THE CLI, both deliberate and both security-driven (see
 * api/schemas_manage.py):
 *
 *   * `fix` is PREVIEW-ONLY over HTTP. The CLI can rewrite a config in place;
 *     the API never writes to files it did not create, because auth is a no-op
 *     unless CASPAR_API_KEY is set. `applied` always comes back false.
 *   * suppression files must be named explicitly. The CLI defaults to
 *     .caspar-suppress.json relative to its cwd, which for a server means
 *     "wherever it happened to be started" — too surprising to inherit.
 *
 * Shapes verified against a live server, not inferred from the schema module.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiDelete, apiGet, apiPost } from "./client";

// ── settings ──────────────────────────────────────────────────────────

/** The server's effective configuration. Read-only by design. */
export interface ServerSettings {
  caspar_version: string;
  db_path: string;
  plugins_dir: string | null;
  data_dir: string | null;
  api_key_required: boolean;
  registered_plugins: string[];
}

/**
 * How the server process was launched — it cannot change while the page is
 * open, so it is never refetched.
 */
export function useServerSettings(): UseQueryResult<ServerSettings> {
  return useQuery({
    queryKey: ["server-settings"],
    queryFn: () => apiGet<ServerSettings>("/settings"),
    staleTime: Infinity,
  });
}

// ── doctor ────────────────────────────────────────────────────────────

export interface DoctorFinding {
  severity: string;
  category: string;
  message: string;
}

export interface DoctorReport {
  healthy: boolean;
  errors: number;
  warnings: number;
  findings: DoctorFinding[];
}

/**
 * Database integrity check.
 *
 * ALWAYS 200 WHEN THE CHECK RAN. The verdict is in `healthy`/`errors`, not in
 * the HTTP status — a report full of findings is a successful request, and
 * rendering it as a failed one would tell the operator the check never
 * happened when in fact it did and it found things.
 */
export function useDoctor(strict: boolean): UseQueryResult<DoctorReport> {
  return useQuery({
    queryKey: ["doctor", strict],
    queryFn: () => apiGet<DoctorReport>("/doctor", { strict }),
  });
}

// ── suppressions ──────────────────────────────────────────────────────

export interface SuppressionItem {
  directive: string;
  reason: string;
  bad_value: string;
  date: string;
}

export interface CreateSuppressionInput {
  directive: string;
  reason: string;
  bad_value?: string;
}

/**
 * The accepted risks in a suppression file.
 *
 * `suppressFile` is a path on the SERVER and the API deliberately has no
 * default, so the query stays disabled until one is given — an empty path
 * would otherwise 400 on every render.
 */
export function useSuppressions(
  suppressFile: string,
): UseQueryResult<SuppressionItem[]> {
  return useQuery({
    queryKey: ["suppressions", suppressFile],
    queryFn: () =>
      apiGet<SuppressionItem[]>("/suppressions", { suppress_file: suppressFile }),
    enabled: Boolean(suppressFile),
  });
}

/** Accept a risk. `reason` is mandatory server-side; the form enforces it too. */
export function useCreateSuppression(suppressFile: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSuppressionInput) =>
      apiPost<SuppressionItem>("/suppressions", {
        ...input,
        bad_value: input.bad_value ?? "",
        suppress_file: suppressFile,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["suppressions", suppressFile] }),
  });
}

/** Withdraw an accepted risk, so it counts against thresholds again. */
export function useDeleteSuppression(suppressFile: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (directive: string) =>
      apiDelete<{ removed: number }>(
        `/suppressions/${encodeURIComponent(directive)}` +
          `?suppress_file=${encodeURIComponent(suppressFile)}`,
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["suppressions", suppressFile] }),
  });
}

// ── fix (preview only) ────────────────────────────────────────────────

export interface FixEdit {
  file: string;
  line_number: number;
  directive: string;
  old_line: string;
  new_line: string;
}

/** A change the tool will not make for you — it needs a human decision. */
export interface FixManualStep {
  directive: string;
  good_value: string;
  reason: string;
  recommendation: string;
  score: number;
}

export interface FixPreview {
  target_name: string | null;
  edits: FixEdit[];
  manual: FixManualStep[];
  diff: string;
  /** Always false over HTTP — applying stays `caspar fix --in-place`. */
  applied: boolean;
}

/**
 * The remediation diff for a config file.
 *
 * A mutation rather than a query because it RE-SCANS the file server-side: it
 * is a request to compute something now, not a cacheable read of stored state.
 * Nothing is written.
 */
export function useFixPreview() {
  return useMutation({
    mutationFn: (input: { input_path: string; live: boolean }) =>
      apiPost<FixPreview>("/fix/preview", input),
  });
}

// ── promote ───────────────────────────────────────────────────────────

export interface PromoteStatsRow {
  target: string;
  rules: number;
  promoted: number;
  needs_review: number;
}

/** The learning-loop scoreboard behind `caspar promote --stats`. */
export function usePromoteStats(): UseQueryResult<PromoteStatsRow[]> {
  return useQuery({
    queryKey: ["promote-stats"],
    queryFn: () => apiGet<PromoteStatsRow[]>("/promote/stats"),
  });
}
