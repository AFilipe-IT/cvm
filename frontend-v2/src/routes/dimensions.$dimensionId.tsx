import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { useState } from "react";
import { CircleSlash, PlayCircle } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import { SeverityDonut, TrendArea } from "@/components/cvm/charts";
import { FindingDetail, FindingRow } from "@/components/cvm/findings";
import {
  Delta,
  Panel,
  PanelHeader,
  Score,
  SeverityBadge,
  TimeStamp,
} from "@/components/cvm/primitives";
import { TechIcon } from "@/components/cvm/primitives";
import { useDimension } from "@/lib/cvm/api";
import { ErrorState, LoadingState } from "@/components/cvm/states";
import { DIMENSION_META, severityVar } from "@/lib/cvm/ui";
import type { DimensionId, Finding, Severity } from "@/lib/cvm/types";

/** The six axes of the model; the API 404s on anything else. */
const DIMENSION_IDS: DimensionId[] = [
  "configuration",
  "permissions",
  "exposure",
  "secrets",
  "patch",
  "hardening",
];

export const Route = createFileRoute("/dimensions/$dimensionId")({
  // Validated against the model's own ids rather than against loaded data: a
  // dimension is a real axis whether or not it has been assessed, so an
  // unassessed one must still route — it renders the "what this would
  // measure" panel — while a misspelling is a genuine 404.
  loader: ({ params }) => {
    if (!DIMENSION_IDS.includes(params.dimensionId as DimensionId)) {
      throw notFound();
    }
    return { id: params.dimensionId as DimensionId };
  },
  // The title no longer carries the score. It used to be derived from the
  // mock, which was available synchronously; the real score arrives after the
  // route renders, and a title claiming a number the page has not fetched
  // would be guesswork.
  head: () => ({ meta: [{ title: "Dimension — CVM" }] }),
  component: DimensionDetail,
});

function DimensionDetail() {
  const { id } = Route.useLoaderData();
  const { data: d, isLoading, error } = useDimension(id);
  const meta = DIMENSION_META[id];
  const Icon = meta.icon;
  const items = d?.findings ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const current = items.find((f) => f.id === selected) ?? items[0];

  // The label is only known once the dimension loads, so the shell falls back
  // to the static one from DIMENSION_META rather than rendering an empty title.
  if (isLoading) {
    return (
      <AppShell title={meta.short}>
        <LoadingState label="Loading dimension…" />
      </AppShell>
    );
  }
  if (error || !d) {
    return (
      <AppShell title={meta.short}>
        <ErrorState error={error} />
      </AppShell>
    );
  }

  if (d.status === "not_assessed") {
    return (
      <AppShell title={d.label} subtitle="Dimension not assessed">
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="rounded-xl border border-dashed border-border bg-panel-alt/40 p-6 lg:col-span-1">
            <span className="inline-flex size-11 items-center justify-center rounded-lg bg-panel text-muted-foreground">
              <Icon className="size-5" />
            </span>
            <div className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-2 py-0.5 text-[11px] text-muted-foreground">
              <CircleSlash className="size-3" /> Not assessed
            </div>
            <div className="num mt-3 text-5xl font-semibold text-faint">N/A</div>
            <p className="mt-3 text-sm text-muted-foreground">{d.description}</p>
            <p className="mt-3 text-xs text-muted-foreground">
              This dimension carries no score, no findings and no delta. The overall posture
              excludes it — a missing measurement is not a clean result.
            </p>
            <button className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-hover">
              <PlayCircle className="size-4" /> Enable collector
            </button>
          </div>
          <Panel className="lg:col-span-2">
            <PanelHeader
              title="What this dimension would measure"
              hint="Rules ship with the knowledge base and are ready to run"
            />
            <ul className="divide-y divide-border">
              {d.would_measure.map((w) => (
                <li key={w} className="flex items-start gap-3 px-5 py-3.5">
                  <span
                    className="mt-1 inline-flex size-6 items-center justify-center rounded-md"
                    style={{
                      color: meta.accent,
                      backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
                    }}
                  >
                    <Icon className="size-3.5" />
                  </span>
                  <span className="text-sm text-muted-foreground">{w}</span>
                </li>
              ))}
            </ul>
            <div className="border-t border-border px-5 py-4 text-xs text-muted-foreground">
              Until this collector runs, any statement about {d.label.toLowerCase()} on these hosts
              is unsupported by evidence.
            </div>
          </Panel>
        </div>
      </AppShell>
    );
  }

  const bands: Severity[] = ["Critical", "High", "Medium", "Low"];

  // The exposure panel is built from the findings' own evidence rather than a
  // separate endpoint: a socket only appears here because a rule fired on it,
  // so the table and the findings list can never disagree.
  const sockets = items.flatMap((finding) => {
    const evidence = finding.evidence;
    return evidence && evidence.kind === "listening_socket"
      ? [{ finding, socket: evidence }]
      : [];
  });
  const dist = bands.map((s) => ({
    severity: s,
    count: items.filter((f) => f.severity === s).length,
  }));

  return (
    <AppShell
      title={d.label}
      subtitle={d.description}
      actions={
        <Link
          to="/findings"
          search={{ dimension: id }}
          className="rounded-lg border border-border bg-panel px-3 py-2 text-sm font-medium hover:bg-panel-alt"
        >
          Open in Findings
        </Link>
      }
    >
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="p-5 xl:col-span-3">
          <div className="flex items-center justify-between">
            <span
              className="inline-flex size-10 items-center justify-center rounded-lg"
              style={{
                color: meta.accent,
                backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
              }}
            >
              <Icon className="size-5" />
            </span>
            <SeverityBadge severity={d.severity} />
          </div>
          <div className="mt-4 flex items-end gap-2">
            <Score value={d.score} severity={d.severity} size="xl" />
            <span className="num pb-2 text-sm text-muted-foreground">risk</span>
          </div>
          <div className="mt-2">
            <Delta value={d.delta} suffix="vs. previous" />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {[
              ["Findings", d.findings_count],
              ["Critical", d.critical_count],
              ["Weight", d.weight?.toFixed(2)],
              ["Targets", new Set(items.map((f) => f.target)).size],
            ].map(([k, v]) => (
              <div key={String(k)} className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2">
                <div className="section-label">{k}</div>
                <div className="num mt-0.5 text-lg font-semibold">{v}</div>
              </div>
            ))}
          </div>
          {d.assessed_at ? (
            <div className="mt-4 border-t border-border pt-3">
              <span className="section-label">Assessed</span> <TimeStamp iso={d.assessed_at} />
            </div>
          ) : null}
        </Panel>

        <Panel className="xl:col-span-6">
          <PanelHeader
            title="Score trend"
            hint={`${(d.trend ?? []).length} assessment${(d.trend ?? []).length === 1 ? "" : "s"}`}
          />
          <div className="px-3 py-4">
            {/* The API names its timestamps `at`; the chart takes `t`. */}
            <TrendArea
              data={(d.trend ?? []).map((p) => ({ t: p.at, score: p.score }))}
              height={196}
            />
          </div>
        </Panel>

        <Panel className="xl:col-span-3">
          <PanelHeader title="Severity breakdown" />
          <div className="px-5 py-3">
            <SeverityDonut data={dist} height={150} />
            <div className="mt-2 space-y-1">
              {dist.map((s) => (
                <div key={s.severity} className="flex items-center gap-2 text-xs">
                  <span
                    className="size-2 rounded-full"
                    style={{ backgroundColor: severityVar(s.severity) }}
                  />
                  <span className="text-muted-foreground">{s.severity}</span>
                  <span className="num ml-auto font-medium">{s.count}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        {id === "exposure" && sockets.length ? (
          <Panel className="xl:col-span-12">
            <PanelHeader
              title="Listening sockets"
              hint="Bound address and owning process, as observed"
            />
            <div className="scroll-x">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border">
                    {["Bound address", "Process", "PID", "Target", "Reachable", "Risk"].map((h) => (
                      <th key={h} className="section-label px-5 py-2 font-semibold">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sockets.map(({ finding, socket }) => (
                    <tr key={finding.id} className="border-b border-border last:border-0">
                      <td className="num px-5 py-2.5 font-mono text-xs">{socket.location}</td>
                      {/* An unresolved owner is shown as unknown, not blank:
                          the socket is real either way, and a blank cell reads
                          as a rendering glitch rather than a limit of what
                          could be observed without root. */}
                      <td className="px-5 py-2.5 font-mono text-xs">
                        {socket.process ?? (
                          <span className="text-muted-foreground">unknown</span>
                        )}
                      </td>
                      <td className="num px-5 py-2.5 font-mono text-xs">
                        {socket.pid ?? <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-5 py-2.5">
                        <span className="flex items-center gap-2">
                          <TechIcon iconKey={finding.target} size="sm" />
                          <span className="text-xs">{finding.target_label}</span>
                        </span>
                      </td>
                      <td className="px-5 py-2.5 text-xs">
                        {socket.world_facing === null ? (
                          <span className="text-muted-foreground">not classified</span>
                        ) : socket.world_facing ? (
                          <span className="text-sev-high">beyond localhost</span>
                        ) : (
                          <span className="text-muted-foreground">localhost only</span>
                        )}
                      </td>
                      <td className="px-5 py-2.5">
                        <span className="flex items-center gap-2">
                          <Score value={finding.score} severity={finding.severity} size="sm" />
                          <SeverityBadge severity={finding.severity} />
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        ) : null}

        <Panel className="xl:col-span-7">
          <PanelHeader title={`Findings · ${items.length}`} />
          <div className="scroll-x">
            <table className="w-full min-w-[620px] text-left">
              <tbody>
                {items.map((f) => (
                  <FindingRow
                    key={f.id}
                    finding={f}
                    selected={current?.id === f.id}
                    onSelect={() => setSelected(f.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel className="xl:col-span-5">
          <PanelHeader title="Finding detail" />
          <div className="px-5 py-4">
            {current ? <FindingDetail finding={current} /> : null}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
