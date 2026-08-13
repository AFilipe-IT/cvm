import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { BookOpen, Link2, Search, X } from "lucide-react";

import { AppShell } from "@/components/cvm/AppShell";
import { Select, Tabs, TextInput } from "@/components/cvm/forms";
import {
  EmptyState,
  Panel,
  PanelHeader,
  Score,
  SeverityBadge,
  Skeleton,
  TechIcon,
} from "@/components/cvm/primitives";
import { ErrorState } from "@/components/cvm/states";
import { useTargets } from "@/lib/cvm/api";
import {
  useBenchmarks,
  useRuleDetail,
  useTargetChains,
  useTargetRules,
  type Rule,
} from "@/lib/cvm/knowledge";
import { severityFor } from "@/lib/cvm/types";

export const Route = createFileRoute("/knowledge")({
  head: () => ({ meta: [{ title: "Knowledge Base — CVM" }] }),
  component: KnowledgePage,
});

type Tab = "rules" | "chains" | "benchmarks";

function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("rules");
  const [target, setTarget] = useState<string>("");
  const [query, setQuery] = useState("");
  const [openRuleId, setOpenRuleId] = useState<string | null>(null);

  const { data: targets, isLoading: targetsLoading } = useTargets();

  // The page is useless without a target, and asking the operator to pick one
  // before seeing anything is friction with no information in it. First target
  // wins until they choose otherwise.
  useEffect(() => {
    if (!target && targets && targets.length) setTarget(targets[0]!.id);
  }, [target, targets]);

  return (
    <AppShell
      title="Knowledge Base"
      subtitle="What CVM knows how to detect — the rules themselves, before any assessment has run."
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="section-label">Target</span>
            <Select
              value={target}
              onChange={(e) => {
                setTarget(e.target.value);
                setOpenRuleId(null);
              }}
              className="min-w-[220px]"
              aria-label="Target"
            >
              {targetsLoading ? <option value="">Loading…</option> : null}
              {(targets ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </Select>
          </label>

          {tab === "rules" ? (
            <label className="flex min-w-[240px] flex-1 flex-col gap-1.5">
              <span className="section-label">Filter</span>
              <span className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <TextInput
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Directive, CCE, or text…"
                  className="!pl-9"
                  aria-label="Filter rules"
                />
              </span>
            </label>
          ) : null}
        </div>

        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "rules", label: "Rules" },
            { id: "chains", label: "Attack chains" },
            { id: "benchmarks", label: "Benchmarks" },
          ]}
        />

        {tab === "rules" ? (
          <RulesPanel target={target} query={query} onOpen={setOpenRuleId} />
        ) : null}
        {tab === "chains" ? <ChainsPanel target={target} /> : null}
        {tab === "benchmarks" ? <BenchmarksPanel /> : null}
      </div>

      {openRuleId ? (
        <RuleDetailPanel
          target={target}
          ruleId={openRuleId}
          onClose={() => setOpenRuleId(null)}
        />
      ) : null}
    </AppShell>
  );
}

// ── rules ──────────────────────────────────────────────────────────────

function RulesPanel({
  target,
  query,
  onOpen,
}: {
  target: string;
  query: string;
  onOpen: (id: string) => void;
}) {
  const { data: rules, isLoading, error } = useTargetRules(target || undefined);

  if (error) return <ErrorState error={error} />;

  const needle = query.trim().toLowerCase();
  const filtered = (rules ?? []).filter((r) =>
    needle
      ? [r.directive, r.bad_value, r.cce_id, r.cis_section, r.justification]
          .join(" ")
          .toLowerCase()
          .includes(needle)
      : true,
  );

  return (
    <Panel>
      <PanelHeader
        title="Rules"
        {...(rules
          ? {
              hint: `${filtered.length} of ${rules.length} rule${
                rules.length === 1 ? "" : "s"
              }`,
            }
          : {})}
      />
      <div className="p-4">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : filtered.length ? (
          <div className="scroll-x">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  {["Directive", "Insecure value", "Score", "CCE", "Section"].map((h) => (
                    <th key={h} className="section-label px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => onOpen(r.id)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onOpen(r.id);
                      }
                    }}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-panel-alt focus-visible:bg-panel-alt focus-visible:outline-none"
                  >
                    <td className="px-3 py-2.5 font-mono text-xs">{r.directive}</td>
                    <td className="max-w-[260px] truncate px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                      {r.bad_value}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-2">
                        <Score
                          value={r.temporal_score}
                          severity={severityFor(r.temporal_score)}
                          size="sm"
                        />
                        <SeverityBadge severity={severityFor(r.temporal_score)} />
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                      {r.cce_id || "—"}
                    </td>
                    <td className="px-3 py-2.5 text-[11px] text-muted-foreground">
                      {r.cis_section || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={BookOpen}
            title={query ? "No rule matches that filter" : "No rules for this target"}
            description={
              query
                ? "Try a directive name, a CCE identifier, or part of the rationale."
                : "Install a plugin, or run a build, to populate the knowledge base for this target."
            }
          />
        )}
      </div>
    </Panel>
  );
}

// ── rule detail ────────────────────────────────────────────────────────

function RuleDetailPanel({
  target,
  ruleId,
  onClose,
}: {
  target: string;
  ruleId: string;
  onClose: () => void;
}) {
  const { data: rule, isLoading } = useRuleDetail(target || undefined, ruleId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        aria-label="Close rule detail"
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <aside
        role="dialog"
        aria-label="Rule detail"
        className="relative flex h-full w-full max-w-lg flex-col overflow-y-auto border-l border-border bg-panel shadow-2xl"
      >
        <div className="sticky top-0 flex items-start justify-between gap-3 border-b border-border bg-panel px-4 py-3">
          <div className="min-w-0">
            <div className="section-label">Rule</div>
            <div className="truncate font-mono text-sm font-semibold">
              {rule?.directive ?? "…"}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-md border border-border p-1.5 text-muted-foreground hover:bg-panel-alt"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="space-y-4 p-4">
          {isLoading || !rule ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3">
                <TechIcon iconKey={rule.target_name} size="md" />
                <div className="flex-1">
                  <div className="text-sm">{rule.target_name}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {rule.rule_type === "absence"
                      ? "Absence rule — fires when the directive is missing"
                      : "Value rule — fires on an insecure value"}
                  </div>
                </div>
                <div className="text-right">
                  <Score
                    value={rule.temporal_score}
                    severity={severityFor(rule.temporal_score)}
                    size="md"
                  />
                  <div className="mt-1">
                    <SeverityBadge severity={severityFor(rule.temporal_score)} />
                  </div>
                </div>
              </div>

              <ValueBlock label="Insecure" value={rule.bad_value} tone="critical" />
              {rule.good_value ? (
                <ValueBlock label="Secure" value={rule.good_value} tone="low" />
              ) : null}

              {/* The CCSS vector, spelled out. This is the scoring evidence — a
                  score with no vector behind it is a number the operator has to
                  take on faith. */}
              <div>
                <div className="section-label mb-1.5">CCSS vector</div>
                <div className="grid grid-cols-4 gap-1.5">
                  {[
                    ["AV", rule.av],
                    ["AC", rule.ac],
                    ["Au", rule.au],
                    ["C", rule.c],
                    ["I", rule.i],
                    ["A", rule.a],
                    ["GEL", rule.gel],
                    ["GRL", rule.grl],
                  ].map(([k, v]) => (
                    <div
                      key={k}
                      className="rounded-md border border-border bg-panel-alt/60 px-2 py-1.5 text-center"
                    >
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        {k}
                      </div>
                      <div className="num text-xs font-semibold">{v}</div>
                    </div>
                  ))}
                </div>
                <p className="mt-1.5 text-[11px] text-muted-foreground">
                  Base <span className="num">{rule.base_score.toFixed(1)}</span> ·
                  temporal <span className="num">{rule.temporal_score.toFixed(1)}</span>
                </p>
              </div>

              {rule.justification ? (
                <Prose label="Why this matters" text={rule.justification} />
              ) : null}
              {rule.recommendation ? (
                <Prose label="Remediation" text={rule.recommendation} />
              ) : null}

              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <Meta label="CCE" value={rule.cce_id || "—"} />
                <Meta label="Benchmark section" value={rule.cis_section || "—"} />
                <Meta label="Applies" value={rule.required_when} />
                <Meta
                  label="Extraction confidence"
                  value={`${Math.round(rule.confidence * 100)}%`}
                />
              </div>

              {rule.cves.length ? (
                <div>
                  <div className="section-label mb-1.5">Related CVEs</div>
                  <div className="flex flex-wrap gap-1.5">
                    {rule.cves.map((cve) => (
                      <code
                        key={String(cve)}
                        className="rounded-md border border-border px-2 py-0.5 font-mono text-[11px]"
                      >
                        {String(cve)}
                      </code>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function ValueBlock({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "critical" | "low";
}) {
  const color = tone === "critical" ? "var(--sev-critical)" : "var(--sev-low)";
  return (
    <div>
      <div className="section-label mb-1" style={{ color }}>
        {label}
      </div>
      <pre
        className="scroll-x rounded-lg border px-3 py-2 font-mono text-[11px]"
        style={{
          borderColor: `color-mix(in oklab, ${color} 30%, transparent)`,
          backgroundColor: `color-mix(in oklab, ${color} 7%, transparent)`,
        }}
      >
        {value}
      </pre>
    </div>
  );
}

function Prose({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="section-label mb-1">{label}</div>
      <p className="text-xs leading-relaxed text-muted-foreground">{text}</p>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-panel-alt/60 px-2.5 py-1.5">
      <div className="section-label">{label}</div>
      <div className="mt-0.5 truncate font-mono">{value}</div>
    </div>
  );
}

// ── chains ─────────────────────────────────────────────────────────────

function ChainsPanel({ target }: { target: string }) {
  const { data: chains, isLoading, error } = useTargetChains(target || undefined);

  if (error) return <ErrorState error={error} />;

  return (
    <Panel>
      <PanelHeader
        title="Chain definitions"
      />
      <div className="p-4">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : chains && chains.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {chains.map((c) => (
              <div
                key={c.chain_id}
                className="rounded-lg border border-border bg-panel-alt/60 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {c.chain_id.replace(/[-_]/g, " ")}
                    </div>
                    {c.cross_target ? (
                      <span className="mt-1 inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                        <Link2 className="size-3" /> Crosses targets
                      </span>
                    ) : null}
                  </div>
                  <span className="num shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px] font-semibold">
                    ×{c.amplification.toFixed(2)}
                  </span>
                </div>

                <ol className="mt-2.5 space-y-1">
                  {c.misconfig_directives.map((d, i) => (
                    <li
                      key={`${d}-${i}`}
                      className="flex items-center gap-2 text-[11px]"
                    >
                      <span className="num flex size-4 shrink-0 items-center justify-center rounded-full border border-border text-[9px]">
                        {i + 1}
                      </span>
                      <code className="truncate font-mono">{String(d)}</code>
                    </li>
                  ))}
                </ol>

                {c.justification ? (
                  <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
                    {c.justification}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Link2}
            title="No chains defined for this target"
            description="Chains are declared when a plugin is built; not every technology has them."
          />
        )}
      </div>
    </Panel>
  );
}

// ── benchmarks ─────────────────────────────────────────────────────────

function BenchmarksPanel() {
  const { data: benchmarks, isLoading, error } = useBenchmarks();

  if (error) return <ErrorState error={error} />;

  return (
    <Panel>
      <PanelHeader
        title="Benchmarks"
      />
      <div className="p-4">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : benchmarks && benchmarks.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {benchmarks.map((b) => (
              <div
                key={b.name}
                className="rounded-lg border border-border bg-panel-alt/60 p-3"
              >
                <div className="flex items-center gap-2.5">
                  <TechIcon iconKey={b.name} size="sm" />
                  <span className="truncate text-sm font-medium">{b.name}</span>
                </div>
                <p className="mt-2 break-words text-[11px] text-muted-foreground">
                  {b.benchmark_source || "Source not recorded"}
                </p>
                {b.version ? (
                  <span className="num mt-2 inline-block rounded-md border border-border px-2 py-0.5 text-[11px]">
                    v{b.version}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={BookOpen}
            title="No benchmarks registered"
            description="Install a plugin to record where its rules came from."
          />
        )}
      </div>
    </Panel>
  );
}
