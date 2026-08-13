import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
import { z } from "zod";
import { AppShell } from "@/components/cvm/AppShell";
import { FindingDetail, FindingRow } from "@/components/cvm/findings";
import { EmptyState, Panel, PanelHeader } from "@/components/cvm/primitives";
import { ErrorState, LoadingState } from "@/components/cvm/states";
import { useFindings, usePosture, useTargets } from "@/lib/cvm/api";
import type { DimensionId, Severity } from "@/lib/cvm/types";

const searchSchema = z.object({
  q: z.string().optional(),
  dimension: z.string().optional(),
  target: z.string().optional(),
  severity: z.string().optional(),
});

export const Route = createFileRoute("/findings")({
  validateSearch: searchSchema,
  head: () => ({
    meta: [
      { title: "Findings — CVM" },
      {
        name: "description",
        content:
          "Filterable configuration findings with impact, remediation, exact evidence location and chain membership.",
      },
      { property: "og:title", content: "Findings — CVM" },
      { property: "og:description", content: "Every finding with evidence and provenance." },
    ],
  }),
  component: FindingsPage,
});

const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];

function FindingsPage() {
  const search = Route.useSearch();
  const navigate = useNavigate({ from: "/findings" });
  const [text, setText] = useState(search.q ?? "");
  const [hasCve, setHasCve] = useState(false);
  const [inChain, setInChain] = useState(false);
  const [selected, setSelected] = useState<string | null>(search.q ?? null);

  // Debounced so a query does not leave for every keystroke. Filtering runs
  // on the server (the reference database holds 6323 findings, and shipping
  // them all to filter here would make `total` meaningless under pagination),
  // which makes each keystroke a network round trip rather than a local pass.
  const [debounced, setDebounced] = useState(text);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(text), 250);
    return () => clearTimeout(timer);
  }, [text]);

  const findingsQuery = useFindings({
    dimension: (search.dimension as DimensionId | undefined) ?? null,
    target: search.target ?? null,
    severity: (search.severity as Severity | undefined) ?? null,
    has_cve: hasCve ? true : null,
    in_chain: inChain ? true : null,
    q: debounced.trim() || null,
    limit: 200,
  });
  const postureQuery = usePosture();
  const targetsQuery = useTargets();

  const posture = postureQuery.data;
  const targets = targetsQuery.data ?? [];
  const filtered = findingsQuery.data?.findings ?? [];
  const total = findingsQuery.data?.total ?? 0;

  // The API already returns findings sorted by score, highest first.
  const current = filtered.find((f) => f.id === selected) ?? filtered[0];

  const setParam = (key: "dimension" | "target" | "severity", value: string) =>
    navigate({
      search: (prev) => ({ ...prev, [key]: value || undefined }),
      replace: true,
    });

  const selectClass =
    "rounded-lg border border-border bg-panel px-2.5 py-2 text-xs text-foreground";

  return (
    <AppShell
      title="Findings"
      subtitle={
        posture
          ? `${posture.totals.findings_open} open across ` +
            `${posture.coverage.dimensions_assessed} assessed dimension` +
            `${posture.coverage.dimensions_assessed === 1 ? "" : "s"}`
          : undefined
      }
    >
      <Panel className="mb-4 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search title, identifier, target, id…"
              className="w-full rounded-lg border border-border bg-panel py-2 pl-8 pr-3 text-xs outline-none focus:ring-2 focus:ring-ring/40"
            />
          </div>
          <select
            className={selectClass}
            value={search.dimension ?? ""}
            onChange={(e) => setParam("dimension", e.target.value)}
          >
            <option value="">All dimensions</option>
            {(posture?.dimensions ?? [])
              .filter((d) => d.status === "assessed")
              .map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
          </select>
          <select
            className={selectClass}
            value={search.target ?? ""}
            onChange={(e) => setParam("target", e.target.value)}
          >
            <option value="">All targets</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          <select
            className={selectClass}
            value={search.severity ?? ""}
            onChange={(e) => setParam("severity", e.target.value)}
          >
            <option value="">All severities</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-2 text-xs">
            <input type="checkbox" checked={hasCve} onChange={(e) => setHasCve(e.target.checked)} />
            Has CVE
          </label>
          <label className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-2 text-xs">
            <input type="checkbox" checked={inChain} onChange={(e) => setInChain(e.target.checked)} />
            In chain
          </label>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="xl:col-span-7">
          <PanelHeader
            title={
              // `total` counts everything matching the filters, not the page,
              // so it is the honest number next to "Results".
              total > filtered.length
                ? `Results · ${filtered.length} of ${total}`
                : `Results · ${total}`
            }
            hint="Sorted by risk, highest first"
          />
          {findingsQuery.isLoading ? (
            <LoadingState label="Loading findings…" />
          ) : findingsQuery.error ? (
            <ErrorState error={findingsQuery.error} />
          ) : filtered.length ? (
            <div className="scroll-x">
              <table className="w-full min-w-[680px] text-left">
                <thead>
                  <tr className="border-b border-border">
                    {["Finding", "Dimension", "Risk", "CVE", "Chains"].map((h) => (
                      <th key={h} className="section-label px-4 py-2">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((f) => (
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
          ) : (
            <div className="p-5">
              <EmptyState
                icon={SlidersHorizontal}
                title="No findings match these filters"
                description="Clear a filter or widen the search. Findings appear here as soon as a collector reports a rule violation."
              />
            </div>
          )}
        </Panel>

        <Panel className="h-fit xl:col-span-5">
          <PanelHeader title="Detail" />
          <div className="px-5 py-4">
            {current ? (
              <FindingDetail finding={current} />
            ) : (
              <EmptyState
                icon={Search}
                title="Select a finding"
                description="Pick a row to see impact, remediation, evidence and chain membership."
              />
            )}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
