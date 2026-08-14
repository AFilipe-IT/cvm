export type Severity = "None" | "Low" | "Medium" | "High" | "Critical";

/**
 * Score → severity label.
 *
 * MUST STAY IDENTICAL to `core/engines/scoring.py::severity_label` (CVSS v3 /
 * NVD bands). Most endpoints send `severity` alongside the score and the
 * console should use what the server said; this exists for the knowledge base,
 * where a rule carries `temporal_score` and no label. Diverging here would show
 * the same rule as two different severities on two pages.
 */
export function severityFor(score: number): Severity {
  if (score === 0) return "None";
  if (score < 4) return "Low";
  if (score < 7) return "Medium";
  if (score < 9) return "High";
  return "Critical";
}
export type DimensionId =
  | "configuration"
  | "permissions"
  | "exposure"
  | "secrets"
  | "patch"
  | "hardening";
export type DimensionStatus = "assessed" | "clean" | "not_assessed";

export interface Dimension {
  id: DimensionId;
  label: string;
  status: DimensionStatus;
  score: number | null;
  severity: Severity | null;
  weight: number | null;
  findings_count: number | null;
  critical_count: number | null;
  delta: number | null;
  assessed_at: string | null;
  description: string;
  would_measure: string[];
  // `at`, matching the API's timestamp naming (assessed_at, first_seen). The
  // chart components take `t`, so callers map — see TrendArea's call sites.
  trend?: { at: string; score: number }[];
}

export interface Posture {
  overall: {
    score: number;
    severity: Severity;
    delta: number | null;
    // null when there are no findings: nothing "produced the number", so
    // there is no directive to trace it back to. The API returns null here
    // (see _driver in api/routers/posture.py).
    driver: {
      kind: string;
      dimension: DimensionId;
      label: string;
      finding_id: string;
      score: number;
    } | null;
  };
  coverage: { dimensions_total: number; dimensions_assessed: number; percent: number };
  dimensions: Dimension[];
  // `highest_score` is null with no active chains — max() of nothing.
  chains: {
    active_count: number;
    highest_score: number | null;
    exceeds_overall: boolean;
  };
  totals: {
    targets_assessed: number;
    rules_evaluated: number;
    findings_open: number;
    critical_findings: number;
    related_cves: number;
  };
  scoring_model: { version: string; aggregation: string; missing_dimension_policy: string };
  // All nullable: `db_sha256` is null when the aggregated scans used different
  // knowledge bases (so the aggregate is NOT reproducible from one state), and
  // `cvm_version` is null for scans saved before the manifest was recorded.
  manifest: {
    cvm_version: string | null;
    db_sha256: string | null;
    scoring_model_version: string | null;
  };
  // Null when nothing has been assessed at all.
  assessed_at: string | null;
}

export type Evidence =
  | { kind: "config_file"; location: string; line: number; snippet: string }
  | { kind: "file_metadata"; location: string; mode: string; owner: string; group: string }
  // `process`/`pid` are null when the socket's owning process could not be
  // resolved — /proc is unreadable for another user's socket without root.
  // `world_facing` is decided by the collector, not by parsing `location`.
  | {
      kind: "listening_socket";
      location: string;
      process: string | null;
      pid: number | null;
      world_facing: boolean | null;
    }
  | {
      kind: "package";
      location: string;
      name: string;
      installed_version: string;
      fixed_version: string;
    };

/** One CCSS metric, with the NISTIR 7502 §3.2 weight it contributes. */
export interface ScoringMetric {
  code: string;
  value: string;
  label: string;
  // Null when the stored value is not one the engine recognises — a data
  // problem the panel shows rather than hides behind a plausible default.
  weight: number | null;
  question: string;
}

/** One line of the arithmetic, with the numbers substituted in. */
export interface ScoringStep {
  label: string;
  formula: string;
  substituted: string;
  value: number;
}

/**
 * Why a finding scores what it scores. Null for a finding stored before the
 * vector was recorded: the score still renders, the breakdown is simply not
 * claimed rather than invented.
 */
export interface ScoringExplanation {
  vector: string;
  exploitability: ScoringMetric[];
  impact: ScoringMetric[];
  temporal: ScoringMetric[];
  base_score: number;
  temporal_score: number;
  steps: ScoringStep[];
  // False when the recomputed score disagrees with the stored one, which
  // means the row is stale. Surfaced rather than silently preferring one.
  matches_stored: boolean;
  reference: string;
}

export interface Finding {
  id: string;
  dimension: DimensionId;
  target: string;
  target_label: string;
  identifier: string;
  observed_value: string;
  expected_value: string;
  score: number;
  severity: Severity;
  // Null on rules built without an LLM narrative, and on every deterministic
  // rule. The backend returns null rather than filler precisely so the console
  // can tell "no data" from "data that happens to be short" — see the header
  // of config_assessment/api/findings.py.
  title: string | null;
  impact: string | null;
  recommendation: string | null;
  // The rule's own reason for existing, distinct from `title` even when the
  // two carry the same text: one names the finding, the other says why the
  // benchmark holds it to matter.
  justification: string | null;
  scoring: ScoringExplanation | null;
  // Null for a finding recovered from the knowledge base rather than observed
  // in a scan: it describes what WOULD be a finding, so there is no file that
  // was read and no socket that was seen.
  evidence: Evidence | null;
  cves: string[];
  references: string[];
  in_chains: string[];
  status: "open" | "resolved";
  // Null on findings stored before first_seen was recorded.
  first_seen: string | null;
}

export interface ChainStep {
  order: number;
  finding_id: string;
  dimension: DimensionId;
  identifier: string;
  score: number;
  role: string;
}

export interface Chain {
  id: string;
  title: string;
  score: number;
  severity: Severity;
  active: boolean;
  amplification: number;
  exceeds_overall: boolean;
  cross_dimension: boolean;
  narrative: string;
  steps: ChainStep[];
}

export interface Target {
  id: string;
  label: string;
  icon_key: string;
  version: string;
  score: number | null;
  severity: Severity | null;
  // null when the target was never assessed — no scan at all, or a scan whose
  // knowledge base held no rules. Distinct from 0, which is a real count from a
  // real assessment: "0 findings" is an all-clear, and giving one to a target
  // nothing measured is the false assurance this model exists to prevent.
  findings_count: number | null;
  critical_count: number;
  benchmark: string;
  status: "online" | "offline";
  sparkline: number[];
}

export interface WatchSession {
  id: string;
  target: string;
  target_label: string;
  icon_key: string;
  state: "live" | "stale" | "paused";
  interval: string;
  last_event_at: string;
  score: number;
  severity: Severity;
  sparkline: number[];
}

export interface WatchEvent {
  id: string;
  at: string;
  target_label: string;
  icon_key: string;
  kind: "config_change" | "reassessment" | "new_finding" | "resolved";
  message: string;
  delta: number | null;
}
