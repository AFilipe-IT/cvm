/**
 * src/lib/cvm/knowledge.ts
 * ------------------------
 * The knowledge base itself — what CVM knows, before any scan has run.
 *
 * THIS IS NOT FINDINGS DATA. A rule here is a thing CVM can detect; a finding
 * is a thing it did detect on a host. Conflating the two is how a console ends
 * up telling an operator they have 400 problems when it means the knowledge
 * base has 400 rules. Every read view elsewhere is scan-scoped; this one is not.
 *
 * Shapes come from `core/models.py` (Misconfiguration, AttackChain) via
 * `KnowledgeEngine`, except `Benchmark`, which the engine builds as a bare dict
 * from the `targets` table — three columns, no model.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiDelete, apiGet, apiPost } from "./client";

/** One row per registered target — the provenance behind its rules. */
export interface Benchmark {
  name: string;
  version: string | null;
  benchmark_source: string | null;
}

/**
 * A rule in the knowledge base.
 *
 * The model carries more fields than this — several are runtime-only
 * (`detected_in_scan`, `source_directive`, `version_amplification`) and are
 * meaningless outside a scan, so they are deliberately not declared: reading
 * them here would invite rendering a scan concept on a knowledge-base page.
 */
export interface Rule {
  id: string;
  target_name: string;
  directive: string;
  bad_value: string;
  good_value: string;
  base_score: number;
  temporal_score: number;
  ac: string;
  c: string;
  i: string;
  a: string;
  av: string;
  au: string;
  gel: string;
  grl: string;
  cves: string[];
  cce_id: string;
  cis_section: string;
  justification: string;
  recommendation: string;
  rule_type: string;
  required_when: string;
  confidence: number;
}

/** A chain definition — not an active chain. `active` is false outside a scan. */
export interface ChainDefinition {
  chain_id: string;
  target_name: string;
  misconfig_directives: string[];
  amplification: number;
  justification: string;
  cross_target: boolean;
  active: boolean;
  amplified_score: number;
  /** Who asserted it: the build pipeline, or a person. */
  provenance: "generated" | "manual";
  author: string;
}

/** The request body of `POST /knowledge/chains` — `caspar chain add`. */
export interface ChainCreate {
  target: string;
  directives: string[];
  justification: string;
  chain_id?: string;
  author?: string;
  amplification?: number;
  cross_target?: boolean;
  overwrite?: boolean;
}

export function useBenchmarks(): UseQueryResult<Benchmark[]> {
  return useQuery({
    queryKey: ["knowledge", "benchmarks"],
    queryFn: () => apiGet<Benchmark[]>("/knowledge/benchmarks"),
  });
}

export function useTargetRules(
  target: string | undefined,
  directive?: string,
): UseQueryResult<Rule[]> {
  return useQuery({
    queryKey: ["knowledge", "rules", target, directive ?? null],
    queryFn: () =>
      apiGet<Rule[]>(`/knowledge/targets/${target}/rules`, {
        ...(directive ? { directive } : {}),
      }),
    enabled: Boolean(target),
  });
}

export function useRuleDetail(
  target: string | undefined,
  ruleId: string | undefined,
): UseQueryResult<Rule> {
  return useQuery({
    queryKey: ["knowledge", "rule", target, ruleId],
    queryFn: () => apiGet<Rule>(`/knowledge/targets/${target}/rules/${ruleId}`),
    enabled: Boolean(target) && Boolean(ruleId),
  });
}

export function useTargetChains(
  target: string | undefined,
): UseQueryResult<ChainDefinition[]> {
  return useQuery({
    queryKey: ["knowledge", "chains", target],
    queryFn: () => apiGet<ChainDefinition[]>(`/knowledge/targets/${target}/chains`),
    enabled: Boolean(target),
  });
}

/**
 * What writing a chain invalidates.
 *
 * A new chain changes the knowledge base, and any scan run afterwards can fire
 * it — so the chain views and the posture both go stale. The scans already
 * stored do not change: a chain is matched at scan time, not at read time.
 */
function useInvalidateAfterChainWrite(): () => void {
  const qc = useQueryClient();
  return () => {
    for (const key of ["knowledge", "chains", "posture"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

/**
 * Record a chain by hand — the console half of `caspar chain add`.
 *
 * Validation lives on the server (core/engines/chain_authoring), so the form
 * does not re-implement the rules: a chain the CLI would refuse comes back as
 * a 422 whose message is written for the operator and can be shown verbatim.
 */
export function useCreateChain() {
  const invalidate = useInvalidateAfterChainWrite();
  return useMutation({
    mutationFn: (body: ChainCreate) =>
      apiPost<ChainDefinition>("/knowledge/chains", body),
    onSuccess: invalidate,
  });
}

export function useDeleteChain() {
  const invalidate = useInvalidateAfterChainWrite();
  return useMutation({
    mutationFn: ({ target, chainId }: { target: string; chainId: string }) =>
      apiDelete<void>(`/knowledge/targets/${target}/chains/${chainId}`),
    onSuccess: invalidate,
  });
}
