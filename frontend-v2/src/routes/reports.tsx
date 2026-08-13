import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Download, FileCode2, FileJson, FileText } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { Panel, PanelHeader, TimeStamp } from "@/components/cvm/primitives";
import { posture } from "@/lib/cvm/data";

export const Route = createFileRoute("/reports")({
  head: () => ({
    meta: [
      { title: "Reports — CVM" },
      {
        name: "description",
        content:
          "Generate reproducible posture reports as JSON, SARIF or HTML, stamped with engine version and knowledge base hash.",
      },
      { property: "og:title", content: "Reports — CVM" },
      { property: "og:description", content: "Export posture, findings and attack chains." },
    ],
  }),
  component: ReportsPage,
});

const FORMATS = [
  {
    id: "json",
    label: "JSON",
    icon: FileJson,
    description: "Full posture document, findings and chains exactly as the API returns them.",
  },
  {
    id: "sarif",
    label: "SARIF 2.1.0",
    icon: FileCode2,
    description: "Static analysis interchange format for code scanning and CI gates.",
  },
  {
    id: "html",
    label: "HTML",
    icon: FileText,
    description: "Self-contained report with evidence, remediation and chain compositions.",
  },
] as const;

const HISTORY = [
  { id: "r-4821", at: "2026-08-12T14:34:00Z", format: "JSON", scope: "All targets", size: "412 KB" },
  { id: "r-4809", at: "2026-08-11T08:02:00Z", format: "SARIF", scope: "Configuration", size: "96 KB" },
  { id: "r-4790", at: "2026-08-09T17:41:00Z", format: "HTML", scope: "All targets", size: "1.2 MB" },
];

function ReportsPage() {
  const [format, setFormat] = useState<string>("json");
  const [scope, setScope] = useState("all");

  return (
    <AppShell title="Reports" subtitle="Reproducible exports of the current posture">
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="xl:col-span-7">
          <PanelHeader title="Generate report" />
          <div className="space-y-5 px-5 py-4">
            <div>
              <div className="section-label mb-2">Format</div>
              <div className="grid gap-2 sm:grid-cols-3">
                {FORMATS.map((f) => (
                  <button
                    key={f.id}
                    onClick={() => setFormat(f.id)}
                    className={`rounded-lg border p-3 text-left transition-colors ${
                      format === f.id
                        ? "border-accent bg-accent/8"
                        : "border-border hover:bg-panel-alt"
                    }`}
                  >
                    <f.icon className="size-4 text-accent" />
                    <div className="mt-2 text-sm font-medium">{f.label}</div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{f.description}</p>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="section-label mb-2">Scope</div>
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                className="w-full rounded-lg border border-border bg-panel px-3 py-2 text-sm"
              >
                <option value="all">All targets · all assessed dimensions</option>
                <option value="configuration">Configuration only</option>
                <option value="permissions">Identity & Permissions only</option>
                <option value="exposure">Network Exposure only</option>
                <option value="chains">Attack chains only</option>
              </select>
            </div>

            <div className="rounded-lg border border-border bg-panel-alt/60 px-4 py-3 text-xs text-muted-foreground">
              Reports include only assessed dimensions. Secrets, Software &amp; Patch Intelligence
              and Platform Hardening are marked <span className="font-medium">not assessed</span> in
              the output — never as zero.
            </div>

            <button className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-hover">
              <Download className="size-4" /> Generate report
            </button>
          </div>
        </Panel>

        <div className="space-y-4 xl:col-span-5">
          <Panel>
            <PanelHeader title="Stamped provenance" hint="Included in every export" />
            <dl className="divide-y divide-border">
              {[
                ["Engine", `CVM ${posture.manifest.cvm_version}`],
                ["Knowledge base", `sha256 ${posture.manifest.db_sha256}`],
                ["Scoring model", `v${posture.scoring_model.version} (${posture.scoring_model.aggregation})`],
                ["Coverage", `${posture.coverage.dimensions_assessed}/${posture.coverage.dimensions_total}`],
                ["Rules evaluated", String(posture.totals.rules_evaluated)],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between px-5 py-2.5">
                  <dt className="text-xs text-muted-foreground">{k}</dt>
                  <dd className="num font-mono text-xs">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <Panel>
            <PanelHeader title="Recent exports" />
            <ul className="divide-y divide-border">
              {HISTORY.map((h) => (
                <li key={h.id} className="flex items-center gap-3 px-5 py-3">
                  <FileText className="size-4 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium">
                      {h.format} · {h.scope}
                    </div>
                    <TimeStamp iso={h.at} />
                  </div>
                  <span className="num text-[11px] text-muted-foreground">{h.size}</span>
                  <button className="text-xs font-medium text-accent hover:underline">
                    Download
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
