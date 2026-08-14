import type { ScoringExplanation, ScoringMetric } from "@/lib/cvm/types";

/**
 * Why a finding scores what it scores.
 *
 * A score with no derivation is an assertion the reader has to take on trust.
 * This panel turns it into an argument: which metric was assigned what value,
 * the weight that value contributes, and the two NISTIR 7502 §3.2 formulas with
 * the numbers substituted so the arithmetic can be checked by hand.
 *
 * The numbers come from the API, which recomputes them from the scoring engine
 * rather than reading them off the stored row (see api/scoring_explain.py). A
 * second implementation of the formulas here would eventually disagree with the
 * engine, and a breakdown that contradicts the score it explains is worse than
 * no breakdown at all.
 */

function MetricRow({ metric }: { metric: ScoringMetric }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="num shrink-0 rounded bg-panel-alt px-1.5 py-0.5 text-[11px] font-semibold text-foreground">
          {metric.code}:{metric.value}
        </span>
        <span className="truncate text-xs text-muted-foreground" title={metric.question}>
          {metric.label}
        </span>
      </div>
      {/* A metric the engine does not recognise shows an em dash rather than a
          zero: 0.000 is a real weight (C:N, I:N and A:N all carry it) and
          reusing it for "unknown" would misreport a data problem as a
          deliberate no-impact assignment. */}
      <span className="num shrink-0 text-xs tabular-nums text-foreground">
        {metric.weight === null ? "—" : metric.weight.toFixed(3)}
      </span>
    </div>
  );
}

function MetricGroup({ title, metrics }: { title: string; metrics: ScoringMetric[] }) {
  return (
    <div>
      <div className="section-label">{title}</div>
      <div className="mt-1 divide-y divide-border">
        {metrics.map((m) => (
          <MetricRow key={m.code} metric={m} />
        ))}
      </div>
    </div>
  );
}

export function ScoringPanel({ scoring }: { scoring: ScoringExplanation }) {
  return (
    <div className="rounded-lg border border-border bg-panel-alt/40 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="section-label">How this score was derived</div>
        <span className="num text-[11px] text-muted-foreground">{scoring.vector}</span>
      </div>

      {/* A stale row is worth interrupting for: it means the stored score and
          the current rule disagree, so a reader comparing this panel with the
          number above would otherwise conclude the panel is broken. */}
      {!scoring.matches_stored ? (
        <div className="mt-3 rounded-md border border-sev-medium/40 bg-sev-medium/10 px-3 py-2 text-xs text-foreground">
          The stored score does not match a fresh computation from this vector —
          the finding predates a change to the rule. The derivation below is the
          current one.
        </div>
      ) : null}

      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <MetricGroup title="Exploitability" metrics={scoring.exploitability} />
        <MetricGroup title="Impact" metrics={scoring.impact} />
        <MetricGroup title="Temporal" metrics={scoring.temporal} />
      </div>

      <div className="section-label mt-5">Arithmetic</div>
      {/* Formulas overflow on narrow screens; they scroll inside their own
          container so the page body never scrolls sideways. */}
      <div className="mt-1 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-xs">
          <tbody className="divide-y divide-border">
            {scoring.steps.map((step) => (
              <tr key={step.label}>
                <td className="py-1.5 pr-3 align-top text-muted-foreground">{step.label}</td>
                <td className="num py-1.5 pr-3 align-top text-foreground">{step.substituted}</td>
                <td className="num py-1.5 text-right align-top font-semibold tabular-nums text-foreground">
                  {step.value.toFixed(step.value % 1 === 0 ? 1 : 2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[11px] text-muted-foreground">
        Weights and formulas: {scoring.reference}.
      </div>
    </div>
  );
}
