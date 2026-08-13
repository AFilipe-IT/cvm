import { createFileRoute, Link } from "@tanstack/react-router";
import { AppShell } from "@/components/cvm/AppShell";
import { Panel, Score, SeverityBadge, Sparkline, TechIcon } from "@/components/cvm/primitives";
import { ScoreScaleLegend } from "@/components/cvm/dimensions";
import { useTargets } from "@/lib/cvm/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { severityVar } from "@/lib/cvm/ui";
import { Crosshair } from "lucide-react";

export const Route = createFileRoute("/targets")({
  head: () => ({
    meta: [
      { title: "Assessed Targets — CVM" },
      {
        name: "description",
        content:
          "Assessed technologies with risk score, open findings and the benchmark each was measured against.",
      },
      { property: "og:title", content: "Assessed Targets — CVM" },
      { property: "og:description", content: "Per-technology configuration risk and benchmarks." },
    ],
  }),
  component: TargetsPage,
});

function TargetsPage() {
  const { data: targets, isLoading, error } = useTargets();

  if (isLoading) {
    return (
      <AppShell title="Targets">
        <LoadingState label="Loading targets…" />
      </AppShell>
    );
  }
  if (error || !targets) {
    return (
      <AppShell title="Targets">
        <ErrorState error={error} />
      </AppShell>
    );
  }

  // Never-assessed targets sort to the BOTTOM rather than to 0.0. Treating a
  // missing score as zero would file them among the lowest-risk technologies,
  // which is the same false-assurance mistake the dimension model exists to
  // prevent — one rank down from the whole point of the page.
  const sorted = [...targets].sort((a, b) => {
    if (a.score === null && b.score === null) return a.label.localeCompare(b.label);
    if (a.score === null) return 1;
    if (b.score === null) return -1;
    return b.score - a.score;
  });
  const assessed = targets.filter((t) => t.score !== null).length;

  if (!targets.length) {
    return (
      <AppShell title="Targets">
        <Panel>
          <EmptyState
            title="No targets registered"
            hint="Install a plugin to add targets"
            icon={<Crosshair className="size-5" />}
          />
        </Panel>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Targets"
      subtitle={
        assessed === targets.length
          ? `${assessed} technolog${assessed === 1 ? "y" : "ies"} assessed`
          : `${assessed} of ${targets.length} registered technologies assessed`
      }
    >
      <div className="mb-4">
        <ScoreScaleLegend />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {sorted.map((t) => (
          <Panel key={t.id} className="p-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <TechIcon iconKey={t.icon_key} size="lg" />
                <div>
                  <div className="text-sm font-semibold">{t.label}</div>
                  <div className="num text-[11px] text-muted-foreground">{t.version}</div>
                </div>
              </div>
              {/* "online/offline" would read as service health. This registry
                  knows nothing about whether a service is up — only whether an
                  assessment exists for it. */}
              <span
                className={`inline-flex items-center gap-1.5 text-[11px] ${
                  t.score !== null ? "text-sev-low" : "text-muted-foreground"
                }`}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{
                    backgroundColor: t.score !== null ? "var(--sev-low)" : "var(--sev-none)",
                  }}
                />
                {t.score !== null ? "assessed" : "never assessed"}
              </span>
            </div>

            <div className="mt-4 flex items-end justify-between">
              <div className="flex items-end gap-2">
                <Score value={t.score} severity={t.severity} size="lg" />
                <div className="pb-1">
                  <SeverityBadge severity={t.severity} />
                </div>
              </div>
              <Sparkline data={t.sparkline} color={severityVar(t.severity)} />
            </div>

            {/* "0 findings" on a target that was never assessed would claim a
                clean result for something nobody looked at. */}
            <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
              {t.score !== null ? (
                <>
                  <span className="num">{t.findings_count} findings</span>
                  <span className="num">{t.critical_count} critical</span>
                </>
              ) : (
                <span>No assessment has been run against this target.</span>
              )}
            </div>

            <div className="mt-4 border-t border-border pt-3">
              <div className="section-label">Benchmark</div>
              <div className="mt-0.5 text-xs">{t.benchmark}</div>
            </div>

            <Link
              to="/findings"
              search={{ target: t.id }}
              className="mt-3 inline-block text-xs font-medium text-accent hover:underline"
            >
              View findings
            </Link>
          </Panel>
        ))}
      </div>
    </AppShell>
  );
}
