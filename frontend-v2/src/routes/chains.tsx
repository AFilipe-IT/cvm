import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/cvm/AppShell";
import { ChainCard } from "@/components/cvm/chains";
import { KpiCard, Panel } from "@/components/cvm/primitives";
import { chains, posture } from "@/lib/cvm/data";
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
          value={posture.chains.highest_score.toFixed(1)}
          accent={KPI_ACCENTS.red}
          icon={TrendingUp}
          footnote={`overall posture ${posture.overall.score.toFixed(1)}`}
        />
        <KpiCard label="Cross-dimension" value={cross} accent={KPI_ACCENTS.teal} icon={Layers} footnote="span 2+ dimensions" />
        <KpiCard label="Exceed overall" value={exceeds} accent={KPI_ACCENTS.orange} icon={TrendingUp} footnote="worse than the aggregate" />
      </div>

      <Panel className="mt-4 px-5 py-4">
        <p className="max-w-4xl text-sm text-muted-foreground">
          A chain scores higher than any of its steps because each weakness removes work the
          attacker would otherwise have to do — reconnaissance, credential guessing, or finding a
          path to persistence. Amplification is the multiplier applied to the worst step.
        </p>
      </Panel>

      <div className="mt-4 space-y-4">
        {sorted.map((c) => (
          <div key={c.id} id={c.id} className="scroll-mt-24">
            <ChainCard chain={c} />
          </div>
        ))}
      </div>
    </AppShell>
  );
}
