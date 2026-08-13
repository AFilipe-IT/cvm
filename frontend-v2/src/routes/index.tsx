import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  Bug,
  Crosshair,
  FlaskConical,
  ListChecks,
  ShieldAlert,
  Waypoints,
} from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { DimensionRadar, ScoreGauge, ScoreOverTime, SeverityDonut } from "@/components/cvm/charts";
import { ChainCard } from "@/components/cvm/chains";
import { DimensionRow, ScoreScaleLegend } from "@/components/cvm/dimensions";
import {
  Delta,
  KpiCard,
  Panel,
  PanelHeader,
  Score,
  SeverityBadge,
  Sparkline,
  TechIcon,
  TimeStamp,
} from "@/components/cvm/primitives";
import {
  useActivity,
  useChains,
  useFindings,
  useOverallTrend,
  usePosture,
  useTargets,
} from "@/lib/cvm/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { DIMENSION_META, KPI_ACCENTS, severityVar } from "@/lib/cvm/ui";
import type { DimensionId, Severity } from "@/lib/cvm/types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Security Posture Overview — CVM" },
      {
        name: "description",
        content:
          "CVM measures configuration risk across six dimensions and detects attack chains. Higher scores mean higher risk.",
      },
      { property: "og:title", content: "Security Posture Overview — CVM" },
      {
        property: "og:description",
        content: "Configuration Vulnerability Meter: risk scoring, evidence and attack chains.",
      },
    ],
  }),
  component: Overview,
});

const severityCounts = (
  items: { severity: Severity }[],
): { severity: Severity; count: number }[] => {
  const order: Severity[] = ["Critical", "High", "Medium", "Low"];
  return order.map((s) => ({
    severity: s,
    count: items.filter((f) => f.severity === s).length,
  }));
};

/** Clockwise from top, per spec. */
const RADAR_ORDER: DimensionId[] = [
  "configuration",
  "secrets",
  "exposure",
  "hardening",
  "patch",
  "permissions",
];

function Overview() {
  const postureQuery = usePosture();
  // The API sorts by score and applies the limit, so the console does not
  // fetch thousands of findings to display eight.
  const findingsQuery = useFindings({ limit: 200 });
  const chainsQuery = useChains();
  const targetsQuery = useTargets();
  const trendQuery = useOverallTrend();
  const activityQuery = useActivity();

  const p = postureQuery.data;
  const findings = findingsQuery.data?.findings ?? [];
  const chains = chainsQuery.data ?? [];
  const targets = targetsQuery.data ?? [];

  // The whole page is a reading of one posture, so it waits for that rather
  // than rendering panels that would each have to invent a placeholder score.
  if (postureQuery.isLoading) {
    return (
      <AppShell title="Overview" subtitle="Infrastructure security posture">
        <LoadingState label="Loading security posture…" />
      </AppShell>
    );
  }
  if (postureQuery.error || !p) {
    return (
      <AppShell title="Overview" subtitle="Infrastructure security posture">
        <ErrorState error={postureQuery.error} />
      </AppShell>
    );
  }

  const topFindings = [...findings].sort((a, b) => b.score - a.score).slice(0, 8);
  const topChains = [...chains].sort((a, b) => b.score - a.score).slice(0, 2);
  const topTargets = [...targets].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 6);

  const radarData = RADAR_ORDER.map((id) => {
    const d = p.dimensions.find((x) => x.id === id);
    return {
      label: d?.label ?? DIMENSION_META[id].short,
      short: DIMENSION_META[id].short,
      // A dimension absent from the response is not plotted at 0 — a broken
      // axis says "not assessed", a zero says "assessed and clean".
      score: d?.score ?? null,
    };
  });

  return (
    <AppShell
      title="Overview"
      subtitle="Infrastructure security posture"
      actions={
        <Link
          to="/chains"
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground hover:bg-accent-hover"
        >
          <Waypoints className="size-3.5" /> Attack chains
        </Link>
      }
    >
      <div className="grid gap-3 xl:grid-cols-12">
        {/* Overall */}
        <div className="space-y-3 xl:col-span-3">
          <Panel>
            <PanelHeader title="Overall risk" />
            <div className="flex flex-col items-center px-3 py-2">
              <ScoreGauge score={p.overall.score} severity={p.overall.severity} size={200} />
              <Delta value={p.overall.delta} suffix="vs. previous" />
              {/* `driver` is null when there are no findings at all — there is
                  then nothing that "produced the number", and inventing a link
                  would point at a finding that does not exist. */}
              {p.overall.driver ? (
                <Link
                  to="/findings"
                  search={{ q: p.overall.driver.finding_id }}
                  className="mt-2 flex w-full items-center gap-2 rounded-md border border-border bg-panel-alt/60 px-2.5 py-1.5 text-[11px] hover:bg-panel-alt"
                >
                  <span className="section-label shrink-0">Driver</span>
                  <span className="truncate font-mono text-[11px]">{p.overall.driver.label}</span>
                  <ArrowRight className="ml-auto size-3 shrink-0 text-accent" />
                </Link>
              ) : null}
            </div>
          </Panel>

          <Panel className="">
            <PanelHeader title="Global risk over time" />
            <div className="px-2 py-2">
              {/* No `boundary` prop: the mock marked where the scoring model
                  changed, but nothing persists a per-scan model version, so
                  that annotation would be a line drawn at a date on which
                  nothing recorded happened. */}
              {trendQuery.isLoading ? (
                <LoadingState label="Loading trend…" />
              ) : (
                <ScoreOverTime data={trendQuery.data ?? []} height={200} />
              )}
            </div>
          </Panel>
        </div>

        {/* KPI row + dimensions */}
        <div className="space-y-3 xl:col-span-6">
          <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
            <KpiCard
              label="Targets"
              value={p.totals.targets_assessed}
              accent={KPI_ACCENTS.blue}
              icon={Crosshair}
              footnote="assessed"
            />
            <KpiCard
              label="Rules"
              value={p.totals.rules_evaluated}
              accent={KPI_ACCENTS.teal}
              icon={FlaskConical}
              footnote="evaluated"
            />
            <KpiCard
              label="Open"
              value={p.totals.findings_open}
              accent={KPI_ACCENTS.orange}
              icon={ListChecks}
              footnote="findings"
            />
            <KpiCard
              label="Critical"
              value={p.totals.critical_findings}
              accent={KPI_ACCENTS.red}
              icon={ShieldAlert}
              footnote="score ≥ 9.0"
            />
            <KpiCard
              label="Chains"
              value={p.chains.active_count}
              accent={KPI_ACCENTS.purple}
              icon={Waypoints}
              footnote={
                <span className="num">
                  {p.chains.highest_score === null
                    ? "none active"
                    : `max ${p.chains.highest_score.toFixed(1)}`}
                </span>
              }
            />
            <KpiCard
              label="CVEs"
              value={p.totals.related_cves}
              accent={KPI_ACCENTS.amber}
              icon={Bug}
              footnote="mapped"
            />
          </div>

          <Panel>
            <PanelHeader
              title="Security dimensions"
              hint="higher = worse"
              action={
                <Link
                  to="/dimensions"
                  className="text-[11px] font-medium text-accent hover:underline"
                >
                  All
                </Link>
              }
            />
            <div className="space-y-1 px-3 py-2">
              {p.dimensions.map((d) => (
                <DimensionRow key={d.id} d={d} />
              ))}
              <div className="pt-1">
                <ScoreScaleLegend />
              </div>
            </div>
          </Panel>
        </div>

        {/* Radar */}
        <div className="space-y-3 xl:col-span-3">
          <Panel>
            <PanelHeader title="Security posture" hint="6 dimensions" />
            <div className="px-2 py-2">
              <DimensionRadar data={radarData} height={286} />
              <p className="px-2 pb-1 text-[11px] text-muted-foreground">
                Not-assessed axes are broken, never plotted as 0.
              </p>
            </div>
          </Panel>

          <Panel className="">
            <PanelHeader title="Severity distribution" />
            <div className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <SeverityDonut data={severityCounts(findings)} height={172} />
              </div>
              <div className="w-28 space-y-1">
                {severityCounts(findings).map((s) => (
                  <div key={s.severity} className="flex items-center gap-1.5 text-[11px]">
                    <span
                      className="size-1.5 rounded-full"
                      style={{ backgroundColor: severityVar(s.severity) }}
                    />
                    <span className="text-muted-foreground">{s.severity}</span>
                    <span className="num ml-auto font-medium">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        </div>

        {/* Chains */}
        <div className="space-y-3 xl:col-span-8">
          <div className="flex items-center justify-between">
            <h2 className="section-label">Top attack chains</h2>
            <Link to="/chains" className="text-[11px] font-medium text-accent hover:underline">
              All {chains.length} chains
            </Link>
          </div>
          {chainsQuery.isLoading ? (
            <Panel>
              <LoadingState label="Loading attack chains…" />
            </Panel>
          ) : topChains.length === 0 ? (
            <Panel>
              <EmptyState
                title="No active attack chains"
                hint="Chains appear when findings combine into a viable path."
                icon={<Waypoints className="size-5" />}
              />
            </Panel>
          ) : (
            topChains.map((c) => <ChainCard key={c.id} chain={c} />)
          )}
        </div>

        <div className="space-y-3 xl:col-span-4">
          <Panel>
            <PanelHeader
              title="Assessed technologies"
              action={
                <Link to="/targets" className="text-[11px] font-medium text-accent hover:underline">
                  All {targets.length}
                </Link>
              }
            />
            <div className="divide-y divide-border">
              {targetsQuery.isLoading ? (
                <LoadingState label="Loading targets…" />
              ) : topTargets.length === 0 ? (
                <EmptyState
                  title="No targets assessed"
                  hint="Run an assessment to populate this list."
                  icon={<Crosshair className="size-5" />}
                />
              ) : null}
              {topTargets.map((t) => (
                <Link
                  key={t.id}
                  to="/findings"
                  search={{ target: t.id }}
                  className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-panel-alt"
                >
                  <TechIcon iconKey={t.icon_key} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium">{t.label}</div>
                    <div className="num truncate text-[11px] text-muted-foreground">
                      {t.version} · {t.findings_count} findings
                    </div>
                  </div>
                  <Sparkline
                    data={t.sparkline}
                    color={severityVar(t.severity)}
                    width={48}
                    height={18}
                  />
                  <Score value={t.score} severity={t.severity} size="sm" />
                </Link>
              ))}
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Recent activity" />
            {activityQuery.isLoading ? (
              <LoadingState label="Loading activity…" />
            ) : (activityQuery.data ?? []).length === 0 ? (
              <EmptyState title="No assessments recorded yet" />
            ) : null}
            <ul className="divide-y divide-border">
              {(activityQuery.data ?? []).map((a) => (
                <li key={a.id} className="flex items-start gap-2 px-3 py-1.5">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" />
                  <div className="min-w-0">
                    <p className="text-[11px] leading-snug">{a.text}</p>
                    <TimeStamp iso={a.at} className="text-[10px]" />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        {/* Top findings */}
        <Panel className="xl:col-span-12">
          <PanelHeader
            title="Top findings by risk"
            action={
              <Link to="/findings" className="text-[11px] font-medium text-accent hover:underline">
                All findings
              </Link>
            }
          />
          <div className="scroll-x">
            <table className="w-full min-w-[720px] text-left">
              <tbody>
                {topFindings.map((f) => (
                  <tr key={f.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-2.5">
                        <TechIcon iconKey={f.target} size="sm" />
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-medium">{f.title ?? f.identifier}</div>
                          <div className="truncate font-mono text-[11px] text-muted-foreground">
                            {f.target_label} · {f.identifier}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Score value={f.score} severity={f.severity} size="sm" />
                        <SeverityBadge severity={f.severity} />
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right">
                      <Link
                        to="/findings"
                        search={{ q: f.id }}
                        className="text-[11px] font-medium text-accent hover:underline"
                      >
                        Detail
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
