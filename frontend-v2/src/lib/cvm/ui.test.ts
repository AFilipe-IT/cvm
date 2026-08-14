import { describe, expect, it } from "vitest";
import { fmtScore, relativeTime, severityForScore, techIcon } from "./ui";

/**
 * The icon lookup, the score formatter, and the clock.
 *
 * All three have the same failure mode: they never throw, they just render
 * something wrong. A missing icon is a grey square, a missing score is a "0",
 * a wrong clock is a plausible age — none of which shows up as an error.
 */

describe("techIcon", () => {
  it("matches the names the API actually returns", () => {
    // The registry says `apache-httpd` and `postgresql`; a map keyed on the
    // short `apache`/`postgres` matched neither, so two INSTALLED plugins
    // rendered as unknown targets.
    expect(techIcon("apache-httpd").label).toBe("Apache HTTPD");
    expect(techIcon("postgresql").label).toBe("PostgreSQL");
    expect(techIcon("azure-iac").label).toBe("Azure IaC");
  });

  it("dresses a catalog target by family when the name is unknown", () => {
    // 43 catalog services are never installed, so none has an exact entry.
    // Without the family layer they all collapsed into the same grey square.
    //
    // Asserting two unknown targets share an icon is NOT enough: before the
    // family layer they shared the generic fallback, so that assertion passed
    // on the broken version. Each family is pinned against the known target it
    // should look like, and against the generic it must no longer be.
    //
    // The comparison is on COLOUR, not glyph: several OS families legitimately
    // share the `Server` glyph with the generic fallback, so an icon check
    // would fail on a correct implementation. Colour is what carries the
    // family identity in that case.
    const generic = techIcon("some-future-target");
    expect(techIcon("rhel9").color).not.toBe(generic.color);
    expect(techIcon("windows-server-2022").color).not.toBe(generic.color);
    expect(techIcon("cisco-ios").color).not.toBe(generic.color);
    expect(techIcon("mongodb").icon).toBe(techIcon("postgresql").icon);
    expect(techIcon("ubuntu2204").color).toBe(techIcon("ubuntu").color);
    expect(techIcon("openshift").icon).toBe(techIcon("kubernetes").icon);
  });

  it("keeps the target's own name as the label while taking the family icon", () => {
    // The family entry is named after the family, so copying it through would
    // make the tooltip claim rhel9 is called "Red Hat family". The icon must
    // still come from the family — otherwise this passes on a plain fallback.
    const rhel = techIcon("rhel9");
    expect(rhel.label).toBe("rhel9");
    expect(rhel.color).toBe(techIcon("rhel8").color);
    expect(rhel.color).not.toBe(techIcon("some-future-target").color);
  });

  it("resolves oracle-linux as an OS, not a database", () => {
    // Order-dependent: /oracle-db/ also matches the substring "oracle", so a
    // families list in the wrong order dresses a Linux host as a cylinder.
    expect(techIcon("oracle-linux-9").icon).toBe(techIcon("rhel8").icon);
    expect(techIcon("oracle-linux-9").icon).not.toBe(techIcon("oracle-db").icon);
  });

  it("still resolves an unknown target instead of failing", () => {
    // A target added to the backend before the console knows about it must
    // render — degraded, not broken.
    const unknown = techIcon("some-future-target");
    expect(unknown.icon).toBeDefined();
    expect(unknown.label).toBe("some-future-target");
  });

  it("is case-insensitive", () => {
    expect(techIcon("NGINX").label).toBe(techIcon("nginx").label);
  });
});

describe("fmtScore", () => {
  it("renders a missing score as a dash, never as zero", () => {
    // This is the project's load-bearing distinction: 0.0 means assessed and
    // clean, null means never assessed. Printing "0.0" for null tells the
    // operator a host is clean when nothing ever looked at it.
    expect(fmtScore(null)).toBe("—");
    expect(fmtScore(0)).toBe("0.0");
  });

  it("keeps one decimal so scores align in a column", () => {
    expect(fmtScore(7)).toBe("7.0");
    expect(fmtScore(9.25)).toBe("9.3");
  });
});

describe("relativeTime", () => {
  // `now` is injectable precisely so the test does not depend on the clock.
  const now = new Date("2026-08-14T12:00:00Z");

  it("reports ages relative to the caller's now", () => {
    expect(relativeTime("2026-08-14T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-08-14T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-08-14T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-08-12T12:00:00Z", now)).toBe("2d ago");
  });
});

describe("severityForScore", () => {
  it("puts a clean score in None rather than Low", () => {
    // A 0.0 host is not "a little bit vulnerable".
    expect(severityForScore(0)).toBe("None");
  });

  it("maps each band at its boundary", () => {
    expect(severityForScore(3.9)).toBe("Low");
    expect(severityForScore(4)).toBe("Medium");
    expect(severityForScore(6.9)).toBe("Medium");
    expect(severityForScore(7)).toBe("High");
    expect(severityForScore(8.9)).toBe("High");
    expect(severityForScore(9)).toBe("Critical");
  });
});
