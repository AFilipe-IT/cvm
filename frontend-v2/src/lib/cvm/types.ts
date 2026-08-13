export type Severity = "None" | "Low" | "Medium" | "High" | "Critical";
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
  trend?: { t: string; score: number }[];
}

export interface Posture {
  overall: {
    score: number;
    severity: Severity;
    delta: number | null;
    driver: { kind: string; dimension: DimensionId; label: string; finding_id: string };
  };
  coverage: { dimensions_total: number; dimensions_assessed: number; percent: number };
  dimensions: Dimension[];
  chains: { active_count: number; highest_score: number; exceeds_overall: boolean };
  totals: {
    targets_assessed: number;
    rules_evaluated: number;
    findings_open: number;
    critical_findings: number;
    related_cves: number;
  };
  scoring_model: { version: string; aggregation: string; missing_dimension_policy: string };
  manifest: { cvm_version: string; db_sha256: string; scoring_model_version: string };
  assessed_at: string;
}

export type Evidence =
  | { kind: "config_file"; location: string; line: number; snippet: string }
  | { kind: "file_metadata"; location: string; mode: string; owner: string; group: string }
  | { kind: "listening_socket"; location: string; process: string; pid: number }
  | {
      kind: "package";
      location: string;
      name: string;
      installed_version: string;
      fixed_version: string;
    };

export interface Finding {
  id: string;
  dimension: DimensionId;
  target: string;
  target_label: string;
  icon_key: string;
  identifier: string;
  observed_value: string;
  expected_value: string;
  score: number;
  severity: Severity;
  title: string;
  impact: string;
  recommendation: string;
  evidence: Evidence;
  cves: string[];
  in_chains: string[];
  status: "open" | "resolved";
  detected_at: string;
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
  findings_count: number;
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
