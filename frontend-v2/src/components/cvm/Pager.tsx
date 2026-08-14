import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Next/previous paging over a known total.
 *
 * Shared by findings, chains and assessment history so the three read and
 * behave identically — the same control in three shapes would drift, and
 * paging is exactly the kind of thing a reader learns once.
 *
 * `total` is the number of items matching the current filters, NOT the number
 * on screen. That distinction is the whole point of the label: "1–10 of 6311"
 * tells the reader the list is a window; "10 results" would let them conclude
 * the estate holds ten findings.
 */
export function Pager({
  total,
  offset,
  pageSize,
  onOffsetChange,
  noun = "results",
  busy = false,
}: {
  total: number;
  offset: number;
  pageSize: number;
  onOffsetChange: (next: number) => void;
  /** Plural noun for the count, e.g. "findings", "chains", "assessments". */
  noun?: string;
  /** Dims the control while the next page loads, without collapsing it. */
  busy?: boolean;
}) {
  // A single page of results needs no controls at all. Rendering a disabled
  // pair of arrows under every short list is noise that never becomes useful.
  if (total <= pageSize) return null;

  const first = offset + 1;
  const last = Math.min(offset + pageSize, total);
  const page = Math.floor(offset / pageSize) + 1;
  const pages = Math.ceil(total / pageSize);
  const atStart = offset <= 0;
  const atEnd = last >= total;

  const button =
    "inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 " +
    "text-xs font-medium transition-colors hover:bg-panel-alt " +
    "disabled:pointer-events-none disabled:opacity-40";

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 ${
        busy ? "opacity-60" : ""
      }`}
    >
      <div className="num text-xs text-muted-foreground tabular-nums">
        {first}–{last} of {total} {noun}
      </div>
      <div className="flex items-center gap-2">
        <span className="num text-xs text-muted-foreground tabular-nums">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          className={button}
          // Clamped at zero: a negative offset is a 422 from the API, and the
          // guard costs less than the error path it removes.
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
          disabled={atStart}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-3.5" /> Previous
        </button>
        <button
          type="button"
          className={button}
          onClick={() => onOffsetChange(offset + pageSize)}
          disabled={atEnd}
          aria-label="Next page"
        >
          Next <ChevronRight className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
