import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowRight, Layers, TrendingUp } from "lucide-react";
import type { Chain } from "@/lib/cvm/types";
import { DIMENSION_META, severityForScore, severityVar } from "@/lib/cvm/ui";
import { Panel, Score, SeverityBadge } from "./primitives";

function StepNode({
  step,
  last,
}: {
  step: Chain["steps"][number];
  last: boolean;
}) {
  const meta = DIMENSION_META[step.dimension];
  const Icon = meta.icon;
  // The step's severity band is derived from its own score rather than looked
  // up on the referenced finding. The score is already on the step, the bands
  // are a fixed function of it, and a lookup would make the colour depend on
  // whether an unrelated query had loaded.
  const severity = severityForScore(step.score);
  return (
    <div className="flex flex-1 items-stretch gap-3 lg:flex-col">
      <div className="flex flex-1 flex-col rounded-lg border border-border bg-panel-alt/60 p-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex size-7 items-center justify-center rounded-lg"
            style={{
              color: meta.accent,
              backgroundColor: `color-mix(in oklab, ${meta.accent} 14%, transparent)`,
            }}
          >
            <Icon className="size-3.5" />
          </span>
          <span className="num text-[11px] font-semibold text-muted-foreground">
            Step {step.order}
          </span>
          <span
            className="ml-auto num text-sm font-semibold"
            style={{ color: severityVar(severity) }}
          >
            {step.score.toFixed(1)}
          </span>
        </div>
        <div className="mt-2 truncate font-mono text-xs font-medium" title={step.identifier}>
          {step.identifier}
        </div>
        {/* The step used to append the finding's target label, resolved from
            the mock. `ChainStep` does not carry it and the dimension plus the
            identifier already name the step; fetching every step's finding to
            add one word would be a query per node. */}
        <div className="mt-0.5 text-[11px]" style={{ color: meta.accent }}>
          {meta.short}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{step.role}</p>
        <Link
          to="/findings"
          search={{ q: step.finding_id }}
          className="mt-2 text-[11px] font-medium text-accent hover:underline"
        >
          View finding {step.finding_id}
        </Link>
      </div>
      {!last ? (
        <div className="flex items-center justify-center text-faint lg:hidden">
          <ArrowDown className="size-4" />
        </div>
      ) : null}
      {!last ? (
        <div className="hidden items-center justify-center lg:flex">
          <ArrowRight className="size-4 text-faint" />
        </div>
      ) : null}
    </div>
  );
}

export function ChainCard({ chain, compact = false }: { chain: Chain; compact?: boolean }) {
  const maxStep = Math.max(...chain.steps.map((s) => s.score));
  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="min-w-0 max-w-2xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-muted-foreground">{chain.id}</span>
            {chain.active ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-sev-critical/12 px-2 py-0.5 text-[11px] font-semibold text-sev-critical">
                <span className="size-1.5 rounded-full bg-sev-critical" />
                Active
              </span>
            ) : null}
            {chain.cross_dimension ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-kpi-purple/12 px-2 py-0.5 text-[11px] font-medium text-kpi-purple">
                <Layers className="size-3" /> Cross-dimension
              </span>
            ) : null}
            {chain.exceeds_overall ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-kpi-orange/12 px-2 py-0.5 text-[11px] font-medium text-kpi-orange">
                <TrendingUp className="size-3" /> Exceeds overall posture
              </span>
            ) : null}
          </div>
          <h3 className="mt-2 text-base font-semibold tracking-tight">{chain.title}</h3>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="section-label">Chain risk</div>
            <div className="mt-1 flex items-center gap-2">
              <Score value={chain.score} severity={chain.severity} size="lg" />
              <SeverityBadge severity={chain.severity} />
            </div>
          </div>
          <div className="hidden text-right sm:block">
            <div className="section-label">Amplification</div>
            <div className="num mt-1 text-lg font-semibold">×{chain.amplification.toFixed(2)}</div>
            <div className="num text-[11px] text-muted-foreground">
              worst step {maxStep.toFixed(1)} → {chain.score.toFixed(1)}
            </div>
          </div>
        </div>
      </div>

      <div className="px-5 py-4">
        <p className="max-w-4xl text-sm leading-relaxed text-muted-foreground">{chain.narrative}</p>

        {!compact ? (
          <>
            <div className="section-label mt-5">Composition · {chain.steps.length} steps</div>
            <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-stretch">
              {chain.steps.map((s, i) => (
                <StepNode key={s.finding_id} step={s} last={i === chain.steps.length - 1} />
              ))}
            </div>
            <div className="mt-4 rounded-lg border border-border bg-panel-alt/60 px-4 py-3 text-xs text-muted-foreground">
              Individually the highest step scores{" "}
              <span className="num font-semibold text-foreground">{maxStep.toFixed(1)}</span>.
              Combined, the chain scores{" "}
              <span
                className="num font-semibold"
                style={{ color: severityVar(chain.severity) }}
              >
                {chain.score.toFixed(1)}
              </span>{" "}
              — the weaknesses remove the work an attacker would otherwise have to do.
            </div>
          </>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {chain.steps.map((s, i) => {
              const meta = DIMENSION_META[s.dimension];
              const Icon = meta.icon;
              return (
                <span key={s.finding_id} className="flex items-center gap-2">
                  <span
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[11px]"
                    style={{
                      color: meta.accent,
                      backgroundColor: `color-mix(in oklab, ${meta.accent} 12%, transparent)`,
                    }}
                  >
                    <Icon className="size-3" />
                    {s.identifier}
                  </span>
                  {i < chain.steps.length - 1 ? (
                    <ArrowRight className="size-3.5 text-faint" />
                  ) : null}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </Panel>
  );
}
