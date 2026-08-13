import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Download, FileCode2, FileJson, FileText, LayoutDashboard } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { Panel, PanelHeader, Score, TimeStamp } from "@/components/cvm/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { usePosture, useScans } from "@/lib/cvm/api";
import { API_BASE } from "@/lib/cvm/client";
import type { Severity } from "@/lib/cvm/types";

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

/**
 * The four formats `POST /scans/{id}/report` actually renders.
 *
 * `ext` and `mime` drive the download, because the endpoint returns a bare
 * body with no Content-Disposition — the filename is the console's job.
 */
const FORMATS = [
  {
    id: "json",
    label: "JSON",
    icon: FileJson,
    ext: "json",
    description: "The scan result exactly as stored, including every finding and chain.",
  },
  {
    id: "sarif",
    label: "SARIF 2.1.0",
    icon: FileCode2,
    ext: "sarif.json",
    description: "Static analysis interchange format for code scanning and CI gates.",
  },
  {
    id: "html",
    label: "HTML",
    icon: FileText,
    ext: "html",
    description: "Self-contained report with evidence, remediation and chain compositions.",
  },
  {
    id: "dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    ext: "html",
    description: "Interactive single-file report with charts rendered inline.",
  },
] as const;

type FormatId = (typeof FORMATS)[number]["id"];

function ReportsPage() {
  const scansQuery = useScans(50);
  const postureQuery = usePosture();
  const scans = scansQuery.data ?? [];
  const posture = postureQuery.data;

  const [format, setFormat] = useState<FormatId>("json");
  const [scanId, setScanId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // Defaults to the most recent scan, which is what "the current posture"
  // means for an export.
  const selected = scans.find((s) => s.id === scanId) ?? scans[0];

  /**
   * Reports are generated on demand and never stored, so this posts, holds the
   * body in memory and hands it to the browser as a download. There is no
   * report id to link to afterwards.
   */
  const generate = async () => {
    if (!selected) return;
    const spec = FORMATS.find((f) => f.id === format);
    if (!spec) return;

    setBusy(true);
    setFailure(null);
    try {
      const response = await fetch(`${API_BASE}/scans/${selected.id}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format, online: false }),
      });
      if (!response.ok) {
        throw new Error(`The engine refused the export (HTTP ${response.status}).`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `cvm-${selected.target_name}-${selected.id.slice(0, 8)}.${spec.ext}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setFailure(
        cause instanceof Error ? cause.message : "The report could not be generated.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell title="Reports" subtitle="Reproducible exports of a stored assessment">
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="xl:col-span-7">
          <PanelHeader title="Generate report" />
          {scansQuery.isLoading ? (
            <LoadingState label="Loading assessments…" />
          ) : scansQuery.error ? (
            <ErrorState error={scansQuery.error} />
          ) : scans.length === 0 ? (
            <EmptyState
              title="Nothing to export"
              hint="A report renders a stored assessment. Run one with `caspar scan` and it will appear here."
              icon={<FileText className="size-5" />}
            />
          ) : (
            <div className="space-y-5 px-5 py-4">
              <div>
                <div className="section-label mb-2">Format</div>
                <div className="grid gap-2 sm:grid-cols-2">
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
                {/* Scope is a scan, not a dimension. A report renders one
                    stored assessment; there is no endpoint that exports a
                    slice of one, and offering that choice would imply
                    filtering the engine does not do. */}
                <div className="section-label mb-2">Assessment</div>
                <select
                  value={selected?.id ?? ""}
                  onChange={(e) => setScanId(e.target.value)}
                  className="w-full rounded-lg border border-border bg-panel px-3 py-2 text-sm"
                >
                  {scans.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.target_name} · {s.global_temporal_score.toFixed(1)} ·{" "}
                      {new Date(s.timestamp).toISOString().slice(0, 16).replace("T", " ")} UTC
                    </option>
                  ))}
                </select>
              </div>

              <div className="rounded-lg border border-border bg-panel-alt/60 px-4 py-3 text-xs text-muted-foreground">
                Reports include only assessed dimensions. Anything not assessed is marked{" "}
                <span className="font-medium">not assessed</span> in the output — never as zero.
              </div>

              {failure ? (
                <p className="text-xs text-sev-high">{failure}</p>
              ) : null}

              <button
                onClick={generate}
                disabled={busy || !selected}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
              >
                <Download className="size-4" />
                {busy ? "Generating…" : "Generate report"}
              </button>
            </div>
          )}
        </Panel>

        <div className="space-y-4 xl:col-span-5">
          <Panel>
            <PanelHeader title="Stamped provenance" hint="Included in every export" />
            {postureQuery.isLoading ? (
              <LoadingState label="Loading provenance…" />
            ) : postureQuery.error || !posture ? (
              <ErrorState error={postureQuery.error} />
            ) : (
              <dl className="divide-y divide-border">
                {[
                  ["Engine", `CVM ${posture.manifest.cvm_version ?? "unknown"}`],
                  [
                    "Knowledge base",
                    posture.manifest.db_sha256
                      ? `sha256 ${posture.manifest.db_sha256.slice(0, 16)}`
                      : "mixed across scans",
                  ],
                  [
                    "Scoring model",
                    `v${posture.scoring_model.version} (${posture.scoring_model.aggregation})`,
                  ],
                  [
                    "Coverage",
                    `${posture.coverage.dimensions_assessed}/${posture.coverage.dimensions_total}`,
                  ],
                  ["Rules evaluated", String(posture.totals.rules_evaluated)],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between px-5 py-2.5">
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="num font-mono text-xs">{v}</dd>
                  </div>
                ))}
              </dl>
            )}
          </Panel>

          {/* This panel replaced a "Recent exports" list. Reports are generated
              on demand and never persisted — the SCAN is the durable artifact —
              so an export history would have been a list of files that do not
              exist anywhere the engine can see. */}
          <Panel>
            <PanelHeader title="Assessments available" hint="The exportable artifacts" />
            {scansQuery.isLoading ? (
              <LoadingState label="Loading assessments…" />
            ) : scans.length === 0 ? (
              <EmptyState
                title="No assessments stored"
                icon={<FileText className="size-5" />}
              />
            ) : (
              <ul className="divide-y divide-border">
                {scans.slice(0, 8).map((s) => (
                  <li key={s.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium">{s.target_name}</div>
                      <TimeStamp iso={s.timestamp} />
                    </div>
                    <span className="num text-[11px] text-muted-foreground">
                      {s.total_issues} findings
                    </span>
                    <Score
                      value={s.global_temporal_score}
                      severity={(s.severity as Severity | null) ?? null}
                      size="sm"
                    />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
