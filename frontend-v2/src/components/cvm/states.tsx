/**
 * src/components/cvm/states.tsx
 * -----------------------------
 * Loading, error and empty states.
 *
 * These exist as shared components because the distinction between them is a
 * correctness property of this console, not a cosmetic one. A dashboard that
 * renders 0.0 while it is still fetching, or that shows an empty findings
 * table when the API is unreachable, is telling the operator they are clean —
 * the exact false-assurance failure the `not_assessed` model exists to prevent.
 */

import { AlertTriangle, Loader2, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/cvm/client";
import { cn } from "@/lib/utils";

export function LoadingState({
  label = "Loading…",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-center gap-2 px-3 py-8 text-xs text-muted-foreground",
        className,
      )}
      role="status"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

/**
 * A failed request.
 *
 * The message comes from the API's own error body where there is one, because
 * the backend already writes these for an operator (contract §9) and
 * paraphrasing them here would only add a second, vaguer voice.
 */
export function ErrorState({
  error,
  className,
}: {
  error: unknown;
  className?: string;
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Something went wrong.";

  const unreachable = error instanceof ApiError && error.status === 0;

  return (
    <div
      className={cn(
        "flex flex-col items-center gap-1.5 px-3 py-8 text-center",
        className,
      )}
      role="alert"
    >
      <AlertTriangle className="size-5 text-[var(--sev-high)]" aria-hidden />
      <p className="text-xs font-medium text-foreground">{message}</p>
      {unreachable ? (
        <p className="text-[11px] text-muted-foreground">
          The console is served separately from the API during development.
        </p>
      ) : null}
    </div>
  );
}

/**
 * A successful request that returned nothing.
 *
 * Deliberately worded as "nothing has been assessed" rather than "no problems
 * found": an empty result before any scan has run is an absence of data, and
 * presenting it as a clean bill of health is the failure this model prevents.
 */
export function EmptyState({
  title,
  hint,
  icon,
  className,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-1.5 px-3 py-8 text-center",
        className,
      )}
    >
      <span className="text-muted-foreground" aria-hidden>
        {icon ?? <Inbox className="size-5" />}
      </span>
      <p className="text-xs font-medium text-foreground">{title}</p>
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * The three states in one place, for the common case.
 *
 * `isEmpty` is passed by the caller rather than inferred, because only the
 * caller knows whether an empty array is meaningful — zero findings is a real
 * and good result, zero targets means nothing is installed.
 */
export function QueryBoundary({
  isLoading,
  error,
  isEmpty,
  empty,
  loadingLabel,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  empty?: ReactNode;
  loadingLabel?: string;
  children: ReactNode;
}) {
  if (isLoading) {
    return loadingLabel ? <LoadingState label={loadingLabel} /> : <LoadingState />;
  }
  if (error) return <ErrorState error={error} />;
  if (isEmpty && empty) return <>{empty}</>;
  return <>{children}</>;
}
