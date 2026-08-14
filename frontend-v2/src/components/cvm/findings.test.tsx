import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EvidenceBlock } from "./findings";
import type { Evidence } from "@/lib/cvm/types";

/**
 * Evidence is what makes a finding defensible to an auditor: it says WHERE the
 * problem is, not just what rule fired. Each of the four kinds carries a
 * different shape, and the failure mode is silent — a missing branch renders
 * the wrong block rather than an error, and a null renders as blank or, worse,
 * as a confident wrong value.
 */

describe("EvidenceBlock", () => {
  it("shows the file and line for a configuration directive", () => {
    // "Set ServerTokens to Prod (currently OS)" says what, not where. The
    // location and line number are the half that lets someone go and fix it.
    const evidence: Evidence = {
      kind: "config_file",
      location: "/etc/nginx/nginx.conf",
      line: 42,
      snippet: "server_tokens on;",
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText(/\/etc\/nginx\/nginx\.conf/)).toBeInTheDocument();
    expect(screen.getByText("server_tokens on;")).toBeInTheDocument();
  });

  it("shows mode, owner and group for filesystem metadata", () => {
    // This is the evidence class no config parser can produce — the whole
    // reason the permissions dimension exists.
    const evidence: Evidence = {
      kind: "file_metadata",
      location: "/etc/shadow",
      mode: "0644",
      owner: "root",
      group: "shadow",
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText("/etc/shadow")).toBeInTheDocument();
    expect(screen.getByText("0644")).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText("shadow")).toBeInTheDocument();
  });

  it("says a socket's process is unknown rather than leaving it blank", () => {
    // /proc is unreadable for another user's socket without root, so null is
    // an ordinary outcome. A blank cell reads as "no process", which is a
    // different and false claim.
    const evidence: Evidence = {
      kind: "listening_socket",
      location: "0.0.0.0:22",
      process: null,
      pid: null,
      world_facing: true,
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("off-host")).toBeInTheDocument();
  });

  it("distinguishes a localhost socket from an off-host one", () => {
    // The classification comes from the collector. Substring-matching
    // "0.0.0.0" got the wildcard right but called every concrete LAN address
    // localhost — the exact inversion that matters for exposure.
    const evidence: Evidence = {
      kind: "listening_socket",
      location: "192.168.1.10:5432",
      process: "postgres",
      pid: 812,
      world_facing: false,
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText("localhost")).toBeInTheDocument();
    expect(screen.getByText("postgres")).toBeInTheDocument();
    expect(screen.getByText("812")).toBeInTheDocument();
  });

  it("reports an unclassified socket as unclassified, not as safe", () => {
    // null means the collector did not decide. Rendering that as "localhost"
    // would turn an unknown into an all-clear.
    const evidence: Evidence = {
      kind: "listening_socket",
      location: "[::]:443",
      process: "nginx",
      pid: 1,
      world_facing: null,
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText("not classified")).toBeInTheDocument();
    expect(screen.queryByText("localhost")).not.toBeInTheDocument();
    expect(screen.queryByText("off-host")).not.toBeInTheDocument();
  });

  it("shows installed and fixed versions for a package", () => {
    const evidence: Evidence = {
      kind: "package",
      location: "openssl",
      name: "openssl",
      installed_version: "3.0.2-0ubuntu1.10",
      fixed_version: "3.0.2-0ubuntu1.15",
    };
    render(<EvidenceBlock evidence={evidence} />);

    expect(screen.getByText("3.0.2-0ubuntu1.10")).toBeInTheDocument();
    expect(screen.getByText("3.0.2-0ubuntu1.15")).toBeInTheDocument();
  });
});
