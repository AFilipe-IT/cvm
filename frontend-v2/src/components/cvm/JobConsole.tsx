import { useEffect, useRef } from "react";
import { CheckCircle2, Info, Loader2, XCircle } from "lucide-react";

import { useJob, useJobLogs, type Job, type JobStatus } from "@/lib/cvm/jobs";

/**
 * Live output of a background job.
 *
 * Ported from the v1 console, whose polling and once-only completion handling
 * were already right; what changed is the styling layer, not the behaviour.
 *
 * NO PERCENTAGE BAR. The build cannot report a real progress fraction, so the
 * indicator is indeterminate. A made-up percentage on a job that runs for
 * an hour and forty minutes is worse than none: it invites the operator to
 * plan around a number that means nothing.
 */

const STATUS_STYLE: Record<JobStatus, { label: string; color: string }> = {
  queued: { label: "queued", color: "var(--text-muted)" },
  running: { label: "running", color: "var(--accent)" },
  succeeded: { label: "succeeded", color: "var(--sev-low)" },
  failed: { label: "failed", color: "var(--sev-critical)" },
  cancelled: { label: "cancelled", color: "var(--text-muted)" },
};

export function JobConsole({
  jobId,
  onFinished,
  placeholder,
}: {
  jobId: string | undefined;
  /** Fired once when the job ends, so other views can refresh. */
  onFinished?: (job: Job) => void;
  placeholder?: string;
}) {
  const { data: job } = useJob(jobId);
  const { lines } = useJobLogs(jobId, job?.status);
  const consoleRef = useRef<HTMLDivElement>(null);
  const notifiedRef = useRef<string | null>(null);

  // Keep the newest line in view as output streams in.
  useEffect(() => {
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  // Exactly once per job, not on every poll after it ends — this triggers
  // refetches elsewhere, and repeating it would refetch the console forever.
  useEffect(() => {
    if (!job || notifiedRef.current === job.id) return;
    if (job.status === "succeeded" || job.status === "failed") {
      notifiedRef.current = job.id;
      onFinished?.(job);
    }
  }, [job, onFinished]);

  if (!jobId) {
    return (
      <div className="flex min-h-[180px] items-center justify-center rounded-lg border border-dashed border-border bg-panel-alt/40 px-4 py-6 text-xs text-muted-foreground">
        {placeholder ?? "No job running. Output will stream here."}
      </div>
    );
  }

  const running = job?.status === "queued" || job?.status === "running";
  const status = job ? STATUS_STYLE[job.status] : null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          {running ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {job?.status === "succeeded" ? (
            <CheckCircle2 className="size-3.5" style={{ color: "var(--sev-low)" }} />
          ) : null}
          {job?.status === "failed" ? (
            <XCircle className="size-3.5" style={{ color: "var(--sev-critical)" }} />
          ) : null}
          <code className="font-mono">{jobId.slice(0, 8)}</code>
          {lines.length > 0 ? <span>· {lines.length} lines</span> : null}
        </span>
        {status ? (
          <span
            className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold"
            style={{
              color: status.color,
              backgroundColor: `color-mix(in oklab, ${status.color} 14%, transparent)`,
            }}
          >
            {status.label}
          </span>
        ) : null}
      </div>

      {running ? (
        <div
          className="h-0.5 overflow-hidden rounded-full bg-panel-alt"
          aria-label="Job in progress"
        >
          <div className="job-progress h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-accent" />
        </div>
      ) : null}

      <div
        ref={consoleRef}
        role="log"
        aria-live="polite"
        className="scroll-x max-h-[320px] min-h-[180px] overflow-y-auto rounded-lg border border-border bg-panel-alt/60 px-3 py-2 font-mono text-[11px] leading-relaxed"
      >
        {lines.length === 0 ? (
          <span className="text-muted-foreground">Waiting for output…</span>
        ) : (
          lines.map((l) => (
            <div
              key={l.seq}
              className={
                l.line.startsWith("ERROR:")
                  ? "whitespace-pre-wrap text-sev-critical"
                  : "whitespace-pre-wrap"
              }
            >
              {l.line || " "}
            </div>
          ))
        )}
      </div>

      {job?.error ? (
        <div className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2 text-xs text-sev-critical">
          {job.error}
        </div>
      ) : null}

      {/* A hard technical fact, not a caveat that can be designed away: the
          reloader kills the process, and no thread survives that. */}
      <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <Info className="mt-0.5 size-3 shrink-0" />
        <span>
          Jobs run inside the server process. They survive a browser refresh, but not a
          server restart — <code className="font-mono">caspar serve --reload</code> kills
          running jobs, so avoid <code className="font-mono">--reload</code> while a build
          is in flight.
        </span>
      </p>
    </div>
  );
}
