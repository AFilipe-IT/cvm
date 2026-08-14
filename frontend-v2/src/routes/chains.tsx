import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { z } from "zod";
import { AppShell } from "@/components/cvm/AppShell";
import { ChainCard } from "@/components/cvm/chains";
import { Pager } from "@/components/cvm/Pager";
import { KpiCard, Panel } from "@/components/cvm/primitives";
import { useChains, usePosture } from "@/lib/cvm/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { DIMENSION_META, KPI_ACCENTS } from "@/lib/cvm/ui";
import type { DimensionId, Severity } from "@/lib/cvm/types";
import { Layers, Search, SlidersHorizontal, TrendingUp, Waypoints } from "lucide-react";

const searchSchema = z.object({
  q: z.string().optional(),
  dimension: z.string().optional(),
  severity: z.string().optional(),
  offset: z.coerce.number().int().min(0).optional(),
});

/** Chains are far taller than finding rows, so fewer fit a screen. */
const PAGE_SIZE = 5;

const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];

export const Route = createFileRoute("/chains")({
  validateSearch: searchSchema,
  head: () => ({
    meta: [
      { title: "Attack Chains — CVM" },
      {
        name: "description",
        content:
          "Combinations of moderate weaknesses that together create severe risk, shown step by step.",
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
  const search = Route.useSearch();
  const navigate = useNavigate({ from: "/chains" });
  const chainsQuery = useChains();
  const postureQuery = usePosture();

  const [text, setText] = useState(search.q ?? "");
  const [crossOnly, setCrossOnly] = useState(false);
  const [exceedsOnly, setExceedsOnly] = useState(false);

  const chains = chainsQuery.data ?? [];
  const posture = postureQuery.data;
  const cross = chains.filter((c) => c.cross_dimension).length;
  const exceeds = chains.filter((c) => c.exceeds_overall).length;

  const setOffset = (next: number | undefined) =>
    navigate({ search: (prev) => ({ ...prev, offset: next || undefined }), replace: true });

  const setParam = (key: "dimension" | "severity", value: string) =>
    navigate({
      search: (prev) => ({ ...prev, [key]: value || undefined, offset: undefined }),
      replace: true,
    });

  // Same reason as on the findings page: narrowing the set while parked on a
  // later page yields an empty list that reads as "nothing matches".
  useEffect(() => {
    setOffset(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, crossOnly, exceedsOnly]);

  // Filtering runs here rather than on the server: the endpoint returns every
  // chain in one response (there are tens, not thousands), so a round trip per
  // keystroke would buy nothing. Findings are the opposite case and filter
  // server-side for exactly that reason.
  const needle = text.trim().toLowerCase();
  const matched = chains.filter((c) => {
    if (search.severity && c.severity !== search.severity) return false;
    if (crossOnly && !c.cross_dimension) return false;
    if (exceedsOnly && !c.exceeds_overall) return false;
    if (search.dimension && !c.steps.some((s) => s.dimension === search.dimension)) {
      return false;
    }
    if (!needle) return true;
    // The identifiers are what an operator carries over from a report, so the
    // step identifiers are searchable alongside the chain's own title and id.
    return (
      c.title.toLowerCase().includes(needle) ||
      c.id.toLowerCase().includes(needle) ||
      c.steps.some((s) => s.identifier.toLowerCase().includes(needle))
    );
  });

  const sorted = [...matched].sort((a, b) => b.score - a.score);
  const offset = search.offset ?? 0;
  const page = sorted.slice(offset, offset + PAGE_SIZE);

  const selectClass =
    "rounded-lg border border-border bg-panel px-2.5 py-2 text-xs text-foreground";

  return (
    <AppShell
      title="Attack Chains"
      subtitle="Individually moderate weaknesses that combine into severe risk"
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {/* The KPI keeps reporting the estate, not the filtered view — it is a
            fact about the system, and swapping it for the match count would
            make the headline number move every time a filter is touched. The
            footnote says so when the two differ. */}
        <KpiCard
          label="Active chains"
          value={chains.length}
          accent={KPI_ACCENTS.purple}
          icon={Waypoints}
          footnote={
            sorted.length === chains.length
              ? "currently satisfiable"
              : `${sorted.length} match the filters`
          }
        />
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

      <Panel className="mt-4 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search chain title, id or step identifier…"
              className="w-full rounded-lg border border-border bg-panel py-2 pl-8 pr-3 text-xs outline-none focus:ring-2 focus:ring-ring/40"
            />
          </div>
          <select
            className={selectClass}
            value={search.dimension ?? ""}
            onChange={(e) => setParam("dimension", e.target.value)}
          >
            <option value="">All dimensions</option>
            {(Object.keys(DIMENSION_META) as DimensionId[]).map((id) => (
              <option key={id} value={id}>
                {DIMENSION_META[id].short}
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
            <input
              type="checkbox"
              checked={crossOnly}
              onChange={(e) => setCrossOnly(e.target.checked)}
            />
            Cross-dimension
          </label>
          <label className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-2 text-xs">
            <input
              type="checkbox"
              checked={exceedsOnly}
              onChange={(e) => setExceedsOnly(e.target.checked)}
            />
            Exceeds overall
          </label>
        </div>
      </Panel>

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
            {/* Two different empty states. "No chains at all" is a property of
                the estate; "none match" is a property of the filter bar, and
                telling the reader the estate is clean when they have simply
                over-filtered would be a false all-clear. */}
            {chains.length === 0 ? (
              <EmptyState
                title="No active attack chains"
                icon={<Waypoints className="size-5" />}
              />
            ) : (
              <EmptyState
                title="No chains match these filters"
                hint={`${chains.length} chains exist — clear a filter or widen the search.`}
                icon={<SlidersHorizontal className="size-5" />}
              />
            )}
          </Panel>
        ) : (
          page.map((c) => (
            <div key={c.id} id={c.id} className="scroll-mt-24">
              <ChainCard chain={c} />
            </div>
          ))
        )}
      </div>

      {/* The pager carries its own top rule, so it needs no panel of its own —
          it reads as the foot of the list above it. */}
      {sorted.length > 0 ? (
        <Pager
          total={sorted.length}
          offset={offset}
          pageSize={PAGE_SIZE}
          onOffsetChange={setOffset}
          noun="chains"
        />
      ) : null}
    </AppShell>
  );
}
