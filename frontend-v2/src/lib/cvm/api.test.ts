import { describe, expect, it } from "vitest";
import { scanAssessedSomething } from "./api";

/**
 * A scan against an empty knowledge base produces score 0.0, severity None and
 * 0 issues — byte for byte what a genuinely clean system produces. The two mean
 * the opposite of each other, and this predicate is the one place the console
 * tells them apart before a score reaches the screen.
 *
 * Getting it backwards is silent: no error, no blank cell, just a green zero on
 * a target nothing ever looked at.
 */

// `scanAssessedSomething` takes the row shape `GET /scans` returns. The rest of
// the row is irrelevant to the decision, so it is filled once here.
const row = (rules: number | null) => ({
  id: "s1",
  target_name: "ubuntu2204",
  input_path: "/",
  global_temporal_score: 0,
  severity: "None",
  total_issues: 0,
  timestamp: "2026-08-14T12:00:00Z",
  rules_for_target: rules,
});

describe("scanAssessedSomething", () => {
  it("rejects a scan whose knowledge base held no rules", () => {
    // The whole point: this row's 0.0 is an artefact of having nothing to
    // check, not a measurement.
    expect(scanAssessedSomething(row(0))).toBe(false);
  });

  it("accepts a scan that had rules, even when it found nothing", () => {
    // The inverse error. A target checked against 18 rules that came back
    // clean has earned its 0.0, and hiding it would make every healthy system
    // look unmeasured.
    expect(scanAssessedSomething(row(18))).toBe(true);
  });

  it("accepts a single rule as an assessment", () => {
    // One rule is a thin knowledge base, not an absent one. Only the empty set
    // means no finding was possible.
    expect(scanAssessedSomething(row(1))).toBe(true);
  });

  it("treats an unknown rule count as assessed", () => {
    // null is a scan saved before the manifest carried the count. Reading
    // unknown as "not assessed" would relabel healthy history and train the
    // operator to ignore the warning.
    expect(scanAssessedSomething(row(null))).toBe(true);
  });

  it("rejects the absence of a scan", () => {
    // A target with no scan at all is also unassessed — the same `—` on
    // screen, reached by a different route.
    expect(scanAssessedSomething(undefined)).toBe(false);
  });
});
