/**
 * src/lib/cvm/api.ts
 * ------------------
 * The query hooks the console renders from. This is the seam that replaced
 * `data.ts`'s hard-coded fixtures with the live API.
 *
 * The mock module exported plain values, so a component could write
 * `posture.overall.score` synchronously. Real data has three states — loading,
 * failed, and present — and pretending otherwise is how a console ends up
 * rendering 0.0 while it is still fetching, which reads as "you are clean".
 * Each hook therefore returns TanStack Query's result and the pages handle the
 * states explicitly.
 *
 * SHAPE TRANSLATION IS DELIBERATELY THIN. `CONTRATO_API_V2.md` was written so
 * the API emits what the UI's `types.ts` already declares. Where a hook does
 * map (watch, targets), it is because the endpoint predates the contract, and
 * the mapping is confined to this file rather than spread across components.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiGet } from "./client";
import type {
  Chain,
  Dimension,
  DimensionId,
  Finding,
  Posture,
  Severity,
  Target,
  WatchEvent,
  WatchSession,
} from "./types";

/** Shared cache keys, so a mutation elsewhere can invalidate precisely. */
export const queryKeys = {
  posture: ["posture"] as const,
  dimension: (id: string) => ["dimension", id] as const,
  findings: (filters: FindingFilters) => ["findings", filters] as const,
  targets: ["targets"] as const,
  scans: ["scans"] as const,
  chains: ["chains"] as const,
  watch: ["watch"] as const,
  trends: ["trends"] as const,
};

// ── posture ────────────────────────────────────────────────────────────

export function usePosture(hostId?: number): UseQueryResult<Posture> {
  return useQuery({
    queryKey: [...queryKeys.posture, hostId ?? null],
    queryFn: () => apiGet<Posture>("/posture", { host_id: hostId }),
  });
}

export interface DimensionDetail extends Dimension {
  findings: Finding[];
  severity_breakdown: Record<string, number>;
  not_assessed_reason?: string;
}

export function useDimension(
  dimensionId: DimensionId,
  hostId?: number,
): UseQueryResult<DimensionDetail> {
  return useQuery({
    queryKey: [...queryKeys.dimension(dimensionId), hostId ?? null],
    queryFn: () =>
      apiGet<DimensionDetail>(`/dimensions/${dimensionId}`, { host_id: hostId }),
  });
}

// ── findings ───────────────────────────────────────────────────────────

export interface FindingFilters {
  dimension?: DimensionId | null;
  target?: string | null;
  severity?: Severity | null;
  has_cve?: boolean | null;
  in_chain?: boolean | null;
  q?: string | null;
  host_id?: number | null;
  limit?: number;
  offset?: number;
}

export interface FindingsPage {
  total: number;
  limit: number;
  offset: number;
  findings: Finding[];
}

/**
 * Filtering happens server-side. The reference database holds 6323 findings,
 * so fetching everything to filter in the browser would be slow and would make
 * `total` a lie under pagination.
 */
export function useFindings(
  filters: FindingFilters = {},
): UseQueryResult<FindingsPage> {
  return useQuery({
    queryKey: queryKeys.findings(filters),
    queryFn: () =>
      apiGet<FindingsPage>("/findings", {
        dimension: filters.dimension,
        target: filters.target,
        severity: filters.severity,
        has_cve: filters.has_cve,
        in_chain: filters.in_chain,
        q: filters.q,
        host_id: filters.host_id,
        limit: filters.limit ?? 50,
        offset: filters.offset ?? 0,
      }),
    // Keeps the previous page on screen while the next one loads, so paging
    // and typing in the search box do not blank the table on every keystroke.
    placeholderData: (prev: FindingsPage | undefined) => prev,
  });
}

// ── targets ────────────────────────────────────────────────────────────

interface TargetResponse {
  name: string;
  display_name: string;
  version: string | null;
  benchmark_source: string | null;
  priority: number;
}

interface ScanRow {
  id: string;
  target_name: string;
  input_path: string;
  global_temporal_score: number;
  severity: string | null;
  total_issues: number;
  timestamp: string;
}

/**
 * The registry of assessable targets, joined to the latest scan of each.
 *
 * `GET /targets` lists what the build CAN assess; it holds no scores, because
 * a registered plugin that has never run has no posture. The scores come from
 * `GET /scans`, and a target with no scan keeps `score: null` — distinct from
 * zero, which would claim a clean result for something never examined.
 */
export function useTargets(): UseQueryResult<Target[]> {
  return useQuery({
    queryKey: queryKeys.targets,
    queryFn: async () => {
      const [registered, scans] = await Promise.all([
        apiGet<TargetResponse[]>("/targets"),
        apiGet<ScanRow[]>("/scans", { limit: 500 }),
      ]);

      // Latest scan per target: rows arrive newest-first, so the first one
      // seen for a target name is the one that counts.
      const latest = new Map<string, ScanRow>();
      const history = new Map<string, number[]>();
      for (const row of scans) {
        if (!latest.has(row.target_name)) latest.set(row.target_name, row);
        const series = history.get(row.target_name) ?? [];
        series.push(row.global_temporal_score);
        history.set(row.target_name, series);
      }

      return registered.map<Target>((t) => {
        const scan = latest.get(t.name);
        return {
          id: t.name,
          label: t.display_name || t.name,
          icon_key: t.name,
          version: t.version ?? "",
          score: scan ? scan.global_temporal_score : null,
          severity: (scan?.severity as Severity | undefined) ?? null,
          findings_count: scan?.total_issues ?? 0,
          critical_count: 0,
          benchmark: t.benchmark_source ?? "",
          // Every registered plugin is assessable; "offline" here means no
          // assessment exists yet, not that a service is down.
          status: scan ? "online" : "offline",
          sparkline: (history.get(t.name) ?? []).slice(0, 12).reverse(),
        };
      });
    },
  });
}

// ── scans, chains and the score trend ──────────────────────────────────

export function useScans(limit = 20): UseQueryResult<ScanRow[]> {
  return useQuery({
    queryKey: [...queryKeys.scans, limit],
    queryFn: () => apiGet<ScanRow[]>("/scans", { limit }),
  });
}

/**
 * Active attack chains across the latest assessment.
 *
 * Scoped the same way /posture is, so a chain listed here is one of the
 * `chains.active_count` the posture page reports — not a separate count that
 * happens to agree. With nothing assessed this is an empty list rather than an
 * error: no scan means no chain, which is a result, not a failure.
 */
export function useChains(): UseQueryResult<Chain[]> {
  return useQuery({
    queryKey: queryKeys.chains,
    queryFn: () => apiGet<Chain[]>("/chains"),
  });
}

export interface TrendPoint {
  t: string;
  score: number;
}

/**
 * The overall score over time, from persisted scans.
 *
 * The mock carried a `model` field per point and a `modelBoundary` marking
 * where the scoring model changed. Nothing persists a per-scan scoring-model
 * version, so that annotation is not reconstructible and the console no longer
 * draws it — an invented boundary would put a line on the chart at a date
 * nothing happened.
 */
export function useOverallTrend(limit = 30): UseQueryResult<TrendPoint[]> {
  return useQuery({
    queryKey: [...queryKeys.trends, limit],
    queryFn: async () => {
      const scans = await apiGet<ScanRow[]>("/scans", { limit });
      return scans
        .slice()
        .reverse()
        .map<TrendPoint>((row) => ({
          t: row.timestamp,
          score: row.global_temporal_score,
        }));
    },
  });
}

// ── watch ──────────────────────────────────────────────────────────────

interface WatchSessionResponse {
  watch_session: string;
  target_name: string | null;
  input_path: string | null;
  global_temporal_score: number;
  severity: string | null;
  watch_interval: number | null;
  timestamp: string | null;
  last_seen: string | null;
  live: boolean;
  runner_state: string | null;
}

function watchState(s: WatchSessionResponse): WatchSession["state"] {
  // `runner_state` exists only when this process owns the loop. A session
  // started from the CLI has none, and its liveness is heartbeat-derived —
  // which is why `live` is the fallback rather than an assumption of "stale".
  if (s.runner_state === "paused") return "paused";
  if (s.runner_state === "running") return "live";
  return s.live ? "live" : "stale";
}

function formatInterval(seconds: number | null): string {
  if (!seconds) return "—";
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

export function useWatchSessions(): UseQueryResult<WatchSession[]> {
  return useQuery({
    queryKey: queryKeys.watch,
    queryFn: async () => {
      const sessions = await apiGet<WatchSessionResponse[]>("/watch");

      // The list endpoint carries only the latest score per session, so the
      // series comes from each session's detail. A watch session's whole point
      // is the score MOVING, and a card showing one number cannot show that.
      const series = await Promise.all(
        sessions.map(async (s) => {
          try {
            const detail = await apiGet<WatchDetailResponse>(
              `/watch/${s.watch_session}`,
            );
            // Oldest-first, so the line reads left to right in time.
            return detail.events
              .slice()
              .reverse()
              .map((e) => e.global_temporal_score);
          } catch {
            // One unreadable session must not blank the whole list; the card
            // still shows its score, just without the trend behind it.
            return [];
          }
        }),
      );

      return sessions.map<WatchSession>((s, i) => ({
        id: s.watch_session,
        target: s.target_name ?? "",
        target_label: s.target_name ?? s.input_path ?? s.watch_session,
        icon_key: s.target_name ?? "",
        state: watchState(s),
        interval: formatInterval(s.watch_interval),
        last_event_at: s.last_seen ?? s.timestamp ?? "",
        score: s.global_temporal_score,
        severity: (s.severity as Severity | null) ?? "None",
        sparkline: series[i] ?? [],
      }));
    },
    // A watch session is by definition changing; the list is polled so the
    // state pill does not go stale while the page sits open.
    refetchInterval: 15_000,
  });
}

interface WatchDetailResponse {
  watch_session: string;
  latest: WatchSessionResponse;
  events: {
    scan_id: string | null;
    timestamp: string | null;
    target_name: string | null;
    global_temporal_score: number;
    total_issues: number;
  }[];
}

/**
 * Recent watch activity, flattened across sessions.
 *
 * Each stored event is a whole scan, so the "kind" the UI shows is derived
 * from how the score MOVED between consecutive scans — that is what the data
 * supports. The mock's richer taxonomy (`config_change` vs `new_finding`)
 * distinguishes causes nothing persists, so it is not reconstructed here.
 */
export function useWatchEvents(): UseQueryResult<WatchEvent[]> {
  const sessions = useWatchSessions();
  const ids = (sessions.data ?? []).map((s) => s.id);

  return useQuery({
    queryKey: [...queryKeys.watch, "events", ids],
    queryFn: async () => {
      const details = await Promise.all(
        ids.map((id) => apiGet<WatchDetailResponse>(`/watch/${id}`)),
      );

      const events: WatchEvent[] = [];
      for (const detail of details) {
        // Oldest-first so each event can be compared with the one before it.
        const ordered = detail.events.slice().reverse();
        ordered.forEach((event, index) => {
          const previous = index > 0 ? ordered[index - 1] : null;
          const delta = previous
            ? Number(
                (
                  event.global_temporal_score - previous.global_temporal_score
                ).toFixed(1),
              )
            : null;
          events.push({
            id: event.scan_id ?? `${detail.watch_session}-${index}`,
            at: event.timestamp ?? "",
            target_label: event.target_name ?? detail.watch_session,
            icon_key: event.target_name ?? "",
            kind:
              delta === null || delta === 0
                ? "reassessment"
                : delta > 0
                  ? "new_finding"
                  : "resolved",
            message:
              delta === null || delta === 0
                ? `Reassessed — score ${event.global_temporal_score.toFixed(1)}, ${event.total_issues} findings`
                : delta > 0
                  ? `Score rose to ${event.global_temporal_score.toFixed(1)} (${event.total_issues} findings)`
                  : `Score fell to ${event.global_temporal_score.toFixed(1)} (${event.total_issues} findings)`,
            delta,
          });
        });
      }
      return events
        .sort((a, b) => b.at.localeCompare(a.at))
        .slice(0, 20);
    },
    enabled: ids.length > 0,
  });
}

// ── activity feed ──────────────────────────────────────────────────────

export interface ActivityItem {
  id: string;
  at: string;
  text: string;
  kind: "scan" | "finding" | "chain" | "resolved" | "kb";
}

/**
 * The dashboard's recent-activity list, derived from stored scans.
 *
 * Only `scan` items are produced. The mock also showed knowledge-base updates
 * and chain-activation moments, but nothing records WHEN a chain became active
 * or when the database was rebuilt — those lines would have to be invented,
 * and an activity feed that invents entries is worse than a short one.
 */
export function useActivity(limit = 8): UseQueryResult<ActivityItem[]> {
  return useQuery({
    queryKey: ["activity", limit],
    queryFn: async () => {
      const scans = await apiGet<ScanRow[]>("/scans", { limit });
      return scans.map<ActivityItem>((row) => ({
        id: row.id,
        at: row.timestamp,
        text:
          `Assessment of ${row.target_name} scored ` +
          `${row.global_temporal_score.toFixed(1)} with ${row.total_issues} ` +
          `finding${row.total_issues === 1 ? "" : "s"}`,
        kind: "scan",
      }));
    },
  });
}
