import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/cvm/AppShell";
import { ChainCard } from "@/components/cvm/chains";
import { KpiCard, Panel } from "@/components/cvm/primitives";
import { useChains, usePosture } from "@/lib/cvm/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { KPI_ACCENTS } from "@/lib/cvm/ui";
import { Layers, TrendingUp, Waypoints } from "lucide-react";

export const Route = createFileRoute("/chains")({
  head: () => ({
    meta: [
      { title: "Attack Chains — CVM" },
      {
        name: "description",
        content:
          "Combinations of moderate weaknesses that together create severe risk, shown step by step with amplification.",
      },
      { property: "og:title", content: "Attack Chains — CVM" },
      {
        property: "og:description",
        content: "Ordered chain compositions across configuration, permissions and exposure.",
      },
    ],
  }),
  component: ChainsPage,
});

function ChainsPage() {
  const chainsQuery = useChains();
  const postureQuery = usePosture();

  const chains = chainsQuery.data ?? [];
  const posture = postureQuery.data;
  const sorted = [...chains].sort((a, b) => b.score - a.score);
  const cross = chains.filter((c) => c.cross_dimension).length;
  const exceeds = chains.filter((c) => c.exceeds_overall).length;

  return (
    <AppShell
      title="Attack Chains"
      subtitle="Individually moderate weaknesses that combine into severe risk"
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Active chains" value={chains.length} accent={KPI_ACCENTS.purple} icon={Waypoints} footnote="currently satisfiable" />
        <KpiCard
          label="Highest chain risk"
          value={
            posture?.chains.highest_score != null
              ? posture.chains.highest_score.toFixed(1)
              : "—"
          }
          accent={KPI_ACCENTS.red}
          icon={TrendingUp}
          footnote={
            posture
              ? `overall posture ${posture.overall.score.toFixed(1)}`
              : "overall posture unavailable"
          }
        />
        <KpiCard label="Cross-dimension" value={cross} accent={KPI_ACCENTS.teal} icon={Layers} footnote="span 2+ dimensions" />
        <KpiCard label="Exceed overall" value={exceeds} accent={KPI_ACCENTS.orange} icon={TrendingUp} footnote="worse than the aggregate" />
      </div>

      <div className="mt-4 space-y-4">
        {chainsQuery.isLoading ? (
          <Panel>
            <LoadingState label="Loading attack chains…" />
          </Panel>
        ) : chainsQuery.error ? (
          <Panel>
            <ErrorState error={chainsQuery.error} />
          </Panel>
        ) : sorted.length === 0 ? (
          <Panel>
            <EmptyState
              title="No active attack chains"
              icon={<Waypoints className="size-5" />}
            />
          </Panel>
        ) : (
          sorted.map((c) => (
            <div key={c.id} id={c.id} className="scroll-mt-24">
              <ChainCard chain={c} />
            </div>
          ))
        )}
      </div>
    </AppShell>
  );
}
