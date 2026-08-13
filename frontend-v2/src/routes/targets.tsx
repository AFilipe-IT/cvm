import { createFileRoute, Link } from "@tanstack/react-router";
import { AppShell } from "@/components/cvm/AppShell";
import { Panel, Score, SeverityBadge, Sparkline, TechIcon } from "@/components/cvm/primitives";
import { ScoreScaleLegend } from "@/components/cvm/dimensions";
import { targets } from "@/lib/cvm/data";
import { severityVar } from "@/lib/cvm/ui";

export const Route = createFileRoute("/targets")({
  head: () => ({
    meta: [
      { title: "Assessed Targets — CVM" },
      {
        name: "description",
        content:
          "Twelve assessed technologies with risk score, open findings and the benchmark each was measured against.",
      },
      { property: "og:title", content: "Assessed Targets — CVM" },
      { property: "og:description", content: "Per-technology configuration risk and benchmarks." },
    ],
  }),
  component: TargetsPage,
});

function TargetsPage() {
  const sorted = [...targets].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  return (
    <AppShell title="Targets" subtitle={`${targets.length} technologies assessed`}>
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
              <span
                className={`inline-flex items-center gap-1.5 text-[11px] ${
                  t.status === "online" ? "text-sev-low" : "text-muted-foreground"
                }`}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{
                    backgroundColor: t.status === "online" ? "var(--sev-low)" : "var(--sev-none)",
                  }}
                />
                {t.status}
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

            <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
              <span className="num">{t.findings_count} findings</span>
              <span className="num">{t.critical_count} critical</span>
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
