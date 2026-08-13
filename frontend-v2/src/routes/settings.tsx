import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Copy, Lock } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { Panel, PanelHeader } from "@/components/cvm/primitives";
import { ScoreScaleLegend } from "@/components/cvm/dimensions";
import { posture } from "@/lib/cvm/data";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — CVM" },
      {
        name: "description",
        content: "Console theme, API access and read-only knowledge base manifest for CVM.",
      },
      { property: "og:title", content: "Settings — CVM" },
      { property: "og:description", content: "Theme, API endpoint and knowledge base manifest." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);
  const apply = (next: "light" | "dark") => {
    setTheme(next);
    localStorage.setItem("cvm-theme", next);
    document.documentElement.classList.toggle("dark", next === "dark");
  };

  return (
    <AppShell title="Settings" subtitle="Console preferences and engine provenance">
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Appearance" hint="Theme is applied at token level" />
          <div className="px-5 py-4">
            <div className="grid grid-cols-2 gap-2">
              {(["light", "dark"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => apply(t)}
                  className={`rounded-lg border p-3 text-left text-sm capitalize ${
                    theme === t ? "border-accent bg-accent/8 font-medium" : "border-border hover:bg-panel-alt"
                  }`}
                >
                  {t} theme
                </button>
              ))}
            </div>
            <div className="mt-4">
              <div className="section-label mb-2">Score scale</div>
              <ScoreScaleLegend />
              <p className="mt-2 text-xs text-muted-foreground">
                Scores measure risk. 0.0 means nothing was found; 10.0 means critical. It is not a
                grade and not a percentage.
              </p>
            </div>
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="API" hint="Read the same data this console renders" />
          <div className="space-y-3 px-5 py-4">
            {["GET /api/v1/posture", "GET /api/v1/findings", "GET /api/v1/chains", "GET /api/v1/targets"].map(
              (e) => (
                <div
                  key={e}
                  className="flex items-center justify-between rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
                >
                  <code className="font-mono text-xs">{e}</code>
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={`Copy ${e}`}
                    onClick={() => navigator.clipboard?.writeText(e.split(" ")[1] ?? "")}
                  >
                    <Copy className="size-3.5" />
                  </button>
                </div>
              ),
            )}
            <p className="text-xs text-muted-foreground">
              Requests are authenticated with a bearer token scoped to a single environment.
            </p>
          </div>
        </Panel>

        <Panel className="xl:col-span-2">
          <PanelHeader
            title="Knowledge base"
            hint="Read-only — replaced as a signed bundle"
            action={
              <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Lock className="size-3" /> immutable
              </span>
            }
          />
          <dl className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-3">
            {[
              ["Engine version", `CVM ${posture.manifest.cvm_version}`],
              ["Knowledge base sha256", posture.manifest.db_sha256],
              ["Scoring model", `v${posture.scoring_model.version}`],
              ["Aggregation", posture.scoring_model.aggregation],
              ["Missing dimension policy", posture.scoring_model.missing_dimension_policy],
              ["Rules", `${posture.totals.rules_evaluated} evaluated`],
            ].map(([k, v]) => (
              <div key={k} className="bg-panel px-5 py-3">
                <dt className="section-label">{k}</dt>
                <dd className="num mt-1 font-mono text-xs">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </AppShell>
  );
}
