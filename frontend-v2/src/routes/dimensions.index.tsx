import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, CircleSlash } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { ScoreScaleLegend } from "@/components/cvm/dimensions";
import { Delta, Panel, Score, SeverityBadge, Sparkline, TimeStamp } from "@/components/cvm/primitives";
import { usePosture } from "@/lib/cvm/api";
import { ErrorState, LoadingState } from "@/components/cvm/states";
import { DIMENSION_META, severityVar } from "@/lib/cvm/ui";

export const Route = createFileRoute("/dimensions/")({
  head: () => ({
    meta: [
      { title: "Security Dimensions — CVM" },
      {
        name: "description",
        content:
          "Six security dimensions: configuration, permissions, network exposure, secrets, patch intelligence and platform hardening.",
      },
      { property: "og:title", content: "Security Dimensions — CVM" },
      {
        property: "og:description",
        content: "Per-dimension risk scores, coverage and what has not been assessed.",
      },
    ],
  }),
  component: DimensionsPage,
});

function DimensionsPage() {
  const { data: posture, isLoading, error } = usePosture();

  if (isLoading) {
    return (
      <AppShell title="Dimensions">
        <LoadingState label="Loading dimensions…" />
      </AppShell>
    );
  }
  if (error || !posture) {
    return (
      <AppShell title="Dimensions">
        <ErrorState error={error} />
      </AppShell>
    );
  }

  const assessed = posture.dimensions.filter((d) => d.status !== "not_assessed");
  const missing = posture.dimensions.filter((d) => d.status === "not_assessed");

  return (
    <AppShell
      title="Dimensions"
      subtitle={`${posture.coverage.dimensions_assessed} of ${posture.coverage.dimensions_total} assessed · ${posture.coverage.percent}% coverage`}
    >
      <div className="mb-4">
        <ScoreScaleLegend />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {assessed.map((d) => {
          const meta = DIMENSION_META[d.id];
          const Icon = meta.icon;
          const color = severityVar(d.severity);
          return (
            <Panel key={d.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between">
                <span
                  className="inline-flex size-10 items-center justify-center rounded-lg"
                  style={{
                    color: meta.accent,
                    backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
                  }}
                >
                  <Icon className="size-5" />
                </span>
                <Sparkline data={(d.trend ?? []).map((t) => t.score)} color={color} />
              </div>
              <h2 className="mt-3 text-base font-semibold tracking-tight">{d.label}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{d.description}</p>
              <div className="mt-4 flex items-end gap-3">
                <Score value={d.score} severity={d.severity} size="lg" />
                <div className="pb-1">
                  <SeverityBadge severity={d.severity} />
                </div>
              </div>
              <div className="mt-2">
                <Delta value={d.delta} suffix="vs. previous" />
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                {[
                  ["findings", d.findings_count],
                  ["critical", d.critical_count],
                  ["weight", d.weight?.toFixed(2)],
                ].map(([k, v]) => (
                  <div key={String(k)} className="rounded-lg border border-border bg-panel-alt/60 py-2">
                    <div className="num text-sm font-semibold">{v}</div>
                    <div className="section-label">{k}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                {d.assessed_at ? <TimeStamp iso={d.assessed_at} /> : null}
                <Link
                  to="/dimensions/$dimensionId"
                  params={{ dimensionId: d.id }}
                  className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                >
                  Detail <ArrowRight className="size-3.5" />
                </Link>
              </div>
            </Panel>
          );
        })}

        {missing.map((d) => {
          const meta = DIMENSION_META[d.id];
          const Icon = meta.icon;
          return (
            <div
              key={d.id}
              className="flex flex-col rounded-xl border border-dashed border-border bg-panel-alt/40 p-5"
            >
              <div className="flex items-start justify-between">
                <span className="inline-flex size-10 items-center justify-center rounded-lg bg-panel text-muted-foreground">
                  <Icon className="size-5" />
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  <CircleSlash className="size-3" /> Not assessed
                </span>
              </div>
              <h2 className="mt-3 text-base font-semibold tracking-tight text-muted-foreground">
                {d.label}
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">{d.description}</p>
              <div className="mt-4 flex items-end gap-3">
                <span className="num text-4xl font-semibold leading-none text-faint">N/A</span>
              </div>
              {/* Same single clause as the detail page: excluded, not zero. */}
              <p className="mt-3 text-[11px] text-muted-foreground">
                Excluded from the overall — not counted as zero.
              </p>
              <div className="mt-4 flex items-center justify-end border-t border-border pt-3">
                <Link
                  to="/dimensions/$dimensionId"
                  params={{ dimensionId: d.id }}
                  className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                >
                  What it would measure <ArrowRight className="size-3.5" />
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </AppShell>
  );
}
