import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { DimensionRow } from "./dimensions";
import type { Dimension } from "@/lib/cvm/types";

/**
 * A dimension that was never assessed must not read as a clean one.
 *
 * This is the project's load-bearing distinction, and the console is where it
 * either survives or quietly dies: rendering `0.0` and "0 findings" for an axis
 * nothing ever looked at tells the operator they are safe. The whole dimension
 * model exists to prevent exactly that false assurance, so the row is pinned
 * here rather than left to a visual check.
 */

const BASE: Dimension = {
  id: "configuration",
  label: "Configuration",
  status: "assessed",
  score: 7.4,
  severity: "High",
  weight: 0.3,
  findings_count: 12,
  critical_count: 2,
  delta: -0.6,
  assessed_at: "2026-08-14T10:00:00Z",
  description: "",
  would_measure: [],
};

// DimensionRow renders a <Link>, which needs a router in context. A memory
// router with a permissive root is the smallest thing that satisfies it
// without pulling in the real route tree.
//
// Async because the router mounts its route asynchronously: rendering and
// asserting in the same tick finds an empty <div>, which fails every
// assertion for a reason that has nothing to do with the component.
async function renderRow(d: Dimension) {
  const rootRoute = createRootRoute({ component: () => <DimensionRow d={d} /> });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  // The generated route tree types the real app's routes; this throwaway tree
  // does not match them, and that mismatch is not what is under test.
  const result = render(<RouterProvider router={router as never} />);
  await waitFor(() => expect(screen.getByText(d.label)).toBeInTheDocument());
  return result;
}

describe("DimensionRow", () => {
  it("shows N/A for a never-assessed dimension, never 0.0", async () => {
    await renderRow({
      ...BASE,
      status: "not_assessed",
      score: null,
      severity: null,
      weight: null,
      findings_count: null,
      critical_count: null,
      delta: null,
      assessed_at: null,
    });

    expect(screen.getByText("N/A")).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  });

  it("says a not-assessed dimension is excluded rather than showing a weight", async () => {
    // A weight would imply the axis contributed to the overall. It did not:
    // aggregate_posture renormalises across assessed dimensions only.
    await renderRow({ ...BASE, status: "not_assessed", score: null, weight: null });

    expect(screen.getByText("excl.")).toBeInTheDocument();
    expect(screen.queryByText(/^w /)).not.toBeInTheDocument();
  });

  it("shows 0.0 for a dimension that was assessed and found clean", async () => {
    // The counterpart: 0.0 is a real, earned result and must stay visible.
    // If this rendered as N/A the fix for the above would have destroyed the
    // distinction from the other side.
    await renderRow({ ...BASE, status: "clean", score: 0, severity: "None", findings_count: 0 });

    expect(screen.getByText("0.0")).toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
  });

  it("shows the score and weight of an assessed dimension", async () => {
    await renderRow(BASE);

    expect(screen.getByText("7.4")).toBeInTheDocument();
    expect(screen.getByText("w 0.30")).toBeInTheDocument();
    expect(screen.queryByText("excl.")).not.toBeInTheDocument();
  });

  it("renders a dash for a first assessment rather than a +0.0 delta", async () => {
    // delta === null means there is nothing to compare against. "+0.0" would
    // claim a measured no-change that was never measured.
    await renderRow({ ...BASE, delta: null });

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("signs a worsening delta so direction is readable without the colour", async () => {
    await renderRow({ ...BASE, delta: 1.3 });
    expect(screen.getByText("+1.3")).toBeInTheDocument();
  });
});
