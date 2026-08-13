import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { severityForScore, severityVar } from "@/lib/cvm/ui";
import type { Severity } from "@/lib/cvm/types";
import { SeverityBadge } from "./primitives";

const axisStyle = {
  fontSize: 11,
  fill: "var(--text-faint)",
};

function TooltipShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
      {children}
    </div>
  );
}

/** Large arc gauge. Fills toward critical — higher is worse. */
export function ScoreGauge({
  score,
  severity,
  size = 240,
}: {
  score: number;
  severity: Severity;
  size?: number;
}) {
  const stroke = 14;
  const r = (size - stroke) / 2 - 6;
  const cx = size / 2;
  const cy = size / 2 + 8;
  const start = Math.PI * 0.8;
  const end = Math.PI * 2.2;
  const pt = (a: number) => `${cx + r * Math.cos(a)} ${cy + r * Math.sin(a)}`;
  const arc = (from: number, to: number) =>
    `M ${pt(from)} A ${r} ${r} 0 ${to - from > Math.PI ? 1 : 0} 1 ${pt(to)}`;
  const value = start + ((end - start) * score) / 10;
  const color = severityVar(severity);

  return (
    <div className="relative" style={{ width: size, height: size * 0.82 }}>
      <svg width={size} height={size * 0.86} role="img" aria-label={`Risk score ${score} of 10`}>
        <path
          d={arc(start, end)}
          fill="none"
          stroke="var(--panel-alt)"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        <path
          d={arc(start, value)}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pt-3">
        <span className="num text-6xl font-semibold leading-none tracking-tight" style={{ color }}>
          {score.toFixed(1)}
        </span>
        <span className="mt-1 text-[11px] text-muted-foreground">risk · higher is worse</span>
        <div className="mt-2">
          <SeverityBadge severity={severity} />
        </div>
      </div>
    </div>
  );
}

export function ScoreOverTime({
  data,
  boundary,
  height = 160,
}: {
  data: { t: string; score: number; model?: string }[];
  boundary?: { t: string; from: string; to: string };
  height?: number;
}) {
  // Points from different scoring models are never joined by a line.
  const merged = data.map((d) => ({
    ...d,
    score: boundary && d.model === boundary.from ? null : d.score,
    legacy: boundary && d.model === boundary.from ? d.score : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={merged} margin={{ top: 8, right: 12, bottom: 0, left: -22 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis domain={[0, 10]} ticks={[0, 5, 10]} tick={axisStyle} tickLine={false} axisLine={false} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const p = payload.find((x) => x.value !== null);
            const v = Number(p?.value ?? 0);
            return (
              <TooltipShell>
                <div className="font-medium">{label}</div>
                <div className="num mt-1 flex items-center gap-2">
                  <span style={{ color: severityVar(severityForScore(v)) }}>{v.toFixed(1)}</span>
                  <SeverityBadge severity={severityForScore(v)} />
                </div>
              </TooltipShell>
            );
          }}
        />
        {boundary ? (
          <ReferenceLine
            x={boundary.t}
            stroke="var(--text-faint)"
            strokeDasharray="3 3"
            label={{
              value: `model ${boundary.to}`,
              position: "insideTopLeft",
              fontSize: 9,
              fill: "var(--text-faint)",
            }}
          />
        ) : null}
        {boundary ? (
          <Line
            type="monotone"
            dataKey="legacy"
            stroke="var(--text-faint)"
            strokeWidth={1.5}
            dot={{ r: 1.5 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        ) : null}
        <Line
          type="monotone"
          dataKey="score"
          stroke="var(--kpi-blue)"
          strokeWidth={2}
          dot={{ r: 2 }}
          connectNulls={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Radar across all six dimensions. Not-assessed axes are never plotted as 0. */
export function DimensionRadar({
  data,
  height = 260,
}: {
  data: { label: string; short: string; score: number | null }[];
  height?: number;
}) {
  const plotted = data.map((d) => ({ ...d, value: d.score }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={plotted} outerRadius="58%" margin={{ top: 8, right: 26, bottom: 4, left: 26 }}>
        <PolarGrid stroke="var(--border)" />
        <PolarAngleAxis
          dataKey="short"
          tick={({ payload, x, y, textAnchor }: any) => {
            const item = plotted.find((d) => d.short === payload.value);
            const na = item?.value === null;
            return (
              <text
                x={x}
                y={y}
                textAnchor={textAnchor}
                dominantBaseline="central"
                fontSize={10}
                fill={na ? "var(--text-faint)" : "var(--color-muted-foreground)"}
              >
                <tspan>{payload.value}</tspan>
                {na ? (
                  <tspan x={x} dy="1.05em" fontSize={8.5} fill="var(--text-faint)">
                    n/a
                  </tspan>
                ) : null}
              </text>
            );
          }}
        />
        <PolarRadiusAxis
          domain={[0, 10]}
          ticks={[0, 2.5, 5, 7.5, 10].map((v) => ({ value: v, coordinate: v }))}
          tick={{ fontSize: 9, fill: "var(--text-faint)" }}
          axisLine={false}
        />
        <Radar
          dataKey="value"
          stroke="var(--sev-high)"
          strokeWidth={2}
          fill="var(--sev-high)"
          fillOpacity={0.22}
          connectNulls={false}
          isAnimationActive={false}
          dot={{ r: 2.5, fill: "var(--sev-high)" }}
        />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0]?.payload as { label: string; value: number | null };
            return (
              <TooltipShell>
                <div className="font-medium">{d.label}</div>
                <div className="num mt-1">
                  {d.value === null ? "not assessed" : `${d.value.toFixed(1)} risk`}
                </div>
              </TooltipShell>
            );
          }}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

export function TrendArea({
  data,
  height = 150,
}: {
  data: { t: string; score: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -22 }}>
        <defs>
          <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--kpi-blue)" stopOpacity={0.18} />
            <stop offset="100%" stopColor="var(--kpi-blue)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="t" tick={axisStyle} tickLine={false} axisLine={false} />
        <YAxis domain={[0, 10]} ticks={[0, 5, 10]} tick={axisStyle} tickLine={false} axisLine={false} />
        <Tooltip
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipShell>
                <div className="font-medium">{label}</div>
                <div className="num mt-1">{Number(payload[0]?.value ?? 0).toFixed(1)} risk</div>
              </TooltipShell>
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="score"
          stroke="var(--kpi-blue)"
          strokeWidth={2}
          fill="url(#trendFill)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function SeverityDonut({
  data,
  height = 200,
}: {
  data: { severity: Severity; count: number }[];
  height?: number;
}) {
  const total = data.reduce((a, b) => a + b.count, 0);
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="severity"
            innerRadius="62%"
            outerRadius="88%"
            paddingAngle={2}
            stroke="var(--panel)"
            strokeWidth={2}
            isAnimationActive={false}
          >
            {data.map((d) => (
              <Cell key={d.severity} fill={severityVar(d.severity)} />
            ))}
          </Pie>
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <TooltipShell>
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={payload[0]?.name as Severity} />
                    <span className="num">{payload[0]?.value} findings</span>
                  </div>
                </TooltipShell>
              ) : null
            }
          />
        </PieChart>
      </ResponsiveContainer>
      <div
        className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
        style={{ height }}
      >
        <span className="num text-2xl font-semibold">{total}</span>
        <span className="text-[11px] text-muted-foreground">open findings</span>
      </div>
    </div>
  );
}
