import { Link } from "@tanstack/react-router";
import { CircleSlash } from "lucide-react";
import type { Dimension } from "@/lib/cvm/types";
import { DIMENSION_META, SEVERITY_BANDS, severityVar } from "@/lib/cvm/ui";
import { SeverityBadge, Sparkline } from "./primitives";

export function DimensionRow({ d }: { d: Dimension }) {
  const meta = DIMENSION_META[d.id];
  const Icon = meta.icon;
  const assessed = d.status !== "not_assessed";
  const color = assessed ? severityVar(d.severity) : "var(--text-faint)";

  return (
    <Link
      to="/dimensions/$dimensionId"
      params={{ dimensionId: d.id }}
      className={`flex items-center gap-2.5 rounded-md border px-2.5 py-1.5 transition-colors hover:bg-panel-alt ${
        assessed ? "border-border bg-panel" : "border-dashed border-border bg-panel-alt/40"
      }`}
    >
      <span
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-md"
        style={
          assessed
            ? {
                color: meta.accent,
                backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
              }
            : { color: "var(--text-faint)" }
        }
      >
        <Icon className="size-3.5" />
      </span>
      <span
        className={`min-w-0 flex-1 truncate text-[13px] font-medium ${
          assessed ? "" : "text-muted-foreground"
        }`}
        title={d.label}
      >
        {d.label}
      </span>
      {assessed ? (
        <span className="num w-9 text-right text-sm font-semibold" style={{ color }}>
          {d.score?.toFixed(1)}
        </span>
      ) : (
        <span className="num w-9 text-right text-sm text-faint">N/A</span>
      )}
      <span className="hidden w-[70px] shrink-0 text-right sm:block">
        <SeverityBadge severity={assessed ? d.severity : null} />
      </span>
      <span className="num hidden w-12 shrink-0 text-right text-[11px] text-muted-foreground xl:inline">
        {assessed ? `w ${d.weight?.toFixed(2)}` : "excl."}
      </span>
      <span
        className="num hidden w-10 shrink-0 justify-end whitespace-nowrap text-right text-[11px] font-medium sm:inline"
        title={
          d.delta === null
            ? "No comparable previous measurement — first assessment"
            : d.delta === 0
              ? "No change since the previous assessment"
              : "Change vs. previous assessment"
        }
        style={{
          color:
            d.delta === null || d.delta === 0
              ? "var(--color-muted-foreground)"
              : d.delta > 0
                ? "var(--sev-critical)"
                : "var(--sev-low)",
        }}
      >
        {d.delta === null ? "—" : `${d.delta > 0 ? "+" : ""}${d.delta.toFixed(1)}`}
      </span>
      <span className="hidden w-[58px] shrink-0 justify-end lg:flex">
        {assessed && d.trend ? (
          <Sparkline data={d.trend.map((p) => p.score)} color={color} width={56} height={18} />
        ) : (
          <span className="h-[1px] w-14 border-t border-dashed border-border" />
        )}
      </span>
    </Link>
  );
}

export function ScoreScaleLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
      {SEVERITY_BANDS.map((b) => (
        <span key={b.severity} className="inline-flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ backgroundColor: severityVar(b.severity) }}
          />
          {b.severity} ({b.range})
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <CircleSlash className="size-3" />
        Not assessed
      </span>
    </div>
  );
}
