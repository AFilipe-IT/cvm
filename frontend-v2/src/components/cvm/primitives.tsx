import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  DIMENSION_META,
  techIcon,
  absoluteTime,
  fmtScore,
  relativeTime,
  severityVar,
} from "@/lib/cvm/ui";
import type { DimensionId, Severity } from "@/lib/cvm/types";

export function Panel({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("panel", className)} {...rest}>
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  action,
  hint,
}: {
  title: string;
  action?: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2">
      <div className="flex min-w-0 items-baseline gap-2">
        <h2 className="section-label">{title}</h2>
        {hint ? <p className="truncate text-[11px] normal-case text-muted-foreground">{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function SeverityBadge({
  severity,
  className,
}: {
  severity: Severity | null;
  className?: string;
}) {
  if (!severity) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-md border border-dashed border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground",
          className,
        )}
      >
        Not assessed
      </span>
    );
  }
  const c = severityVar(severity);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold",
        className,
      )}
      style={{ color: c, backgroundColor: `color-mix(in oklab, ${c} 14%, transparent)` }}
    >
      {severity}
    </span>
  );
}

export function Score({
  value,
  severity,
  size = "md",
  className,
}: {
  value: number | null;
  severity: Severity | null;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}) {
  const sizes = {
    sm: "text-base",
    md: "text-2xl",
    lg: "text-4xl",
    xl: "text-6xl",
  } as const;
  return (
    <span
      className={cn("num font-semibold leading-none tracking-tight", sizes[size], className)}
      style={{ color: value === null ? "var(--text-faint)" : severityVar(severity) }}
    >
      {fmtScore(value)}
    </span>
  );
}

export function Delta({ value, suffix }: { value: number | null; suffix?: string }) {
  if (value === null) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <span className="num">—</span>
        <span>first assessment</span>
      </span>
    );
  }
  if (value === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Minus className="size-3" />
        <span className="num">0.0</span>
        <span>no change</span>
      </span>
    );
  }
  const worse = value > 0;
  const color = worse ? "var(--sev-critical)" : "var(--sev-low)";
  const Icon = worse ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color }}>
      <Icon className="size-3.5" />
      <span className="num">
        {worse ? "+" : ""}
        {value.toFixed(1)}
      </span>
      {suffix ? <span className="text-muted-foreground">{suffix}</span> : null}
    </span>
  );
}

export function TechIcon({
  iconKey,
  size = "md",
}: {
  iconKey: string;
  size?: "sm" | "md" | "lg";
}) {
  const meta = techIcon(iconKey);
  const Icon = meta.icon;
  const box = size === "sm" ? "size-7" : size === "lg" ? "size-11" : "size-9";
  const ic = size === "sm" ? "size-3.5" : size === "lg" ? "size-5.5" : "size-4.5";
  return (
    <>
      <span
        className={cn(box, "hidden items-center justify-center rounded-lg dark:inline-flex")}
        style={{
          backgroundColor: `color-mix(in oklab, ${meta.colorDark} 12%, transparent)`,
          color: meta.colorDark,
        }}
      >
        <Icon className={ic} />
      </span>
      <span
        className={cn(box, "inline-flex items-center justify-center rounded-lg dark:hidden")}
        style={{
          backgroundColor: `color-mix(in oklab, ${meta.color} 12%, transparent)`,
          color: meta.color,
        }}
      >
        <Icon className={ic} />
      </span>
    </>
  );
}

export function DimensionChip({
  id,
  label,
  className,
}: {
  id: DimensionId;
  label?: string;
  className?: string;
}) {
  const meta = DIMENSION_META[id];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium",
        className,
      )}
      style={{
        color: meta.accent,
        backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
      }}
    >
      <Icon className="size-3" />
      {label ?? meta.short}
    </span>
  );
}

export function TimeStamp({
  iso,
  className,
}: {
  iso: string | null | undefined;
  className?: string;
}) {
  // Timestamps are genuinely absent in places — a finding stored before
  // first_seen was recorded, a watch session that has not reported yet. Passing
  // those through would render "Invalid Date", which looks like a bug rather
  // than like a missing value.
  if (!iso || Number.isNaN(new Date(iso).getTime())) {
    return (
      <span className={cn("text-xs text-muted-foreground", className)}>unknown</span>
    );
  }
  return (
    <time
      dateTime={iso}
      title={absoluteTime(iso)}
      className={cn("text-xs text-muted-foreground", className)}
    >
      {relativeTime(iso)}
    </time>
  );
}

export function Sparkline({
  data,
  color,
  width = 96,
  height = 28,
}: {
  data: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  // Fewer than two points is not a trend. One point would divide by zero for
  // its x coordinate (NaN, which SVG drops silently); zero points would draw an
  // empty polyline. Reserving the space keeps the row from reflowing once a
  // second assessment gives the line something to say.
  if (data.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / span) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-panel-alt/60 px-6 py-10 text-center">
      <Icon className="size-5 text-muted-foreground" />
      <p className="mt-3 text-sm font-medium">{title}</p>
      <p className="mt-1 max-w-sm text-xs text-muted-foreground">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-panel-alt", className)} />;
}

export function KpiCard({
  label,
  value,
  accent,
  icon: Icon,
  footnote,
}: {
  label: string;
  value: string | number;
  accent: string;
  icon: React.ComponentType<{ className?: string }>;
  footnote?: ReactNode;
}) {
  return (
    <Panel className="px-3 py-2">
      <div className="flex items-start justify-between">
        <span className="section-label">{label}</span>
        <span
          className="inline-flex size-5 items-center justify-center rounded-md"
          style={{
            color: accent,
            backgroundColor: `color-mix(in oklab, ${accent} 12%, transparent)`,
          }}
        >
          <Icon className="size-3.5" />
        </span>
      </div>
      <div className="num mt-1 text-2xl font-semibold leading-none tracking-tight">{value}</div>
      {footnote ? (
        <div className="mt-1 truncate text-[11px] text-muted-foreground">{footnote}</div>
      ) : null}
    </Panel>
  );
}
