import { Link } from "@tanstack/react-router";
import { FileCode2, HardDrive, Network, Package, ShieldAlert, X } from "lucide-react";
import type { Evidence, Finding } from "@/lib/cvm/types";
import { DIMENSION_META, severityVar } from "@/lib/cvm/ui";
import { useChains } from "@/lib/cvm/api";
import { DimensionChip, Score, SeverityBadge, TechIcon, TimeStamp } from "./primitives";

export function EvidenceBlock({ evidence }: { evidence: Evidence }) {
  const head = (icon: React.ReactNode, label: string) => (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground">{icon}</span>
      <span className="section-label">{label}</span>
    </div>
  );

  if (evidence.kind === "config_file") {
    return (
      <div className="rounded-lg border border-border bg-panel-alt/60 p-3">
        {head(<FileCode2 className="size-3.5" />, "Configuration directive")}
        <div className="mt-2 font-mono text-xs">
          {evidence.location}
          <span className="text-muted-foreground">:{evidence.line}</span>
        </div>
        <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-panel px-3 py-2 font-mono text-xs">
          <span className="num mr-3 select-none text-faint">{evidence.line}</span>
          {evidence.snippet}
        </pre>
      </div>
    );
  }

  if (evidence.kind === "file_metadata") {
    return (
      <div className="rounded-lg border border-border bg-panel-alt/60 p-3">
        {head(<HardDrive className="size-3.5" />, "Filesystem metadata")}
        <div className="mt-2 font-mono text-xs">{evidence.location}</div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            ["mode", evidence.mode],
            ["owner", evidence.owner],
            ["group", evidence.group],
          ].map(([k, v]) => (
            <div key={k} className="rounded-md border border-border bg-panel px-2.5 py-1.5">
              <div className="section-label">{k}</div>
              <div className="num mt-0.5 font-mono text-xs">{v}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (evidence.kind === "listening_socket") {
    return (
      <div className="rounded-lg border border-border bg-panel-alt/60 p-3">
        {head(<Network className="size-3.5" />, "Listening socket")}
        <div className="mt-2 font-mono text-xs">{evidence.location}</div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            // Null when the owning process could not be read — /proc is not
            // readable for another user's socket without root.
            ["process", evidence.process ?? "unknown"],
            ["pid", evidence.pid === null ? "—" : String(evidence.pid)],
            // Taken from the collector's own classification. Substring-matching
            // "0.0.0.0" got the wildcard right but called every concrete LAN
            // address localhost — the exact inversion that matters here.
            [
              "reachable",
              evidence.world_facing === null
                ? "not classified"
                : evidence.world_facing
                  ? "off-host"
                  : "localhost",
            ],
          ].map(([k, v]) => (
            <div key={k} className="rounded-md border border-border bg-panel px-2.5 py-1.5">
              <div className="section-label">{k}</div>
              <div className="num mt-0.5 font-mono text-xs">{v}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-panel-alt/60 p-3">
      {head(<Package className="size-3.5" />, "Package")}
      <div className="mt-2 grid grid-cols-3 gap-2">
        {[
          ["name", evidence.name],
          ["installed", evidence.installed_version],
          ["fixed in", evidence.fixed_version],
        ].map(([k, v]) => (
          <div key={k} className="rounded-md border border-border bg-panel px-2.5 py-1.5">
            <div className="section-label">{k}</div>
            <div className="num mt-0.5 font-mono text-xs">{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function FindingDetail({
  finding,
  onClose,
}: {
  finding: Finding;
  onClose?: () => void;
}) {
  // One shared query, already cached by the chains page and the dashboard, so
  // resolving a chain reference costs nothing extra. It only ever ENRICHES the
  // link — the id below renders whether or not this resolves.
  const { data: chains } = useChains();
  const chainById = (id: string) => (chains ?? []).find((c) => c.id === id);
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <TechIcon iconKey={finding.target} size="lg" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <DimensionChip id={finding.dimension} />
              <span className="font-mono text-[11px] text-muted-foreground">{finding.id}</span>
              <TimeStamp iso={finding.first_seen} />
            </div>
            {/* Deterministic rules carry no LLM narrative, so the identifier
                is the heading when there is no title to use. */}
            <h3 className="mt-1.5 text-base font-semibold tracking-tight">
              {finding.title ?? finding.identifier}
            </h3>
            <div className="mt-1 font-mono text-xs text-muted-foreground">
              {finding.target_label} · {finding.identifier}
            </div>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <div className="text-right">
            <Score value={finding.score} severity={finding.severity} size="lg" />
            <div className="mt-1">
              <SeverityBadge severity={finding.severity} />
            </div>
          </div>
          {onClose ? (
            <button
              onClick={onClose}
              aria-label="Close detail"
              className="inline-flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2">
          <div className="section-label">Observed</div>
          <div className="num mt-0.5 font-mono text-xs text-sev-high">{finding.observed_value}</div>
        </div>
        <div className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2">
          <div className="section-label">Expected</div>
          <div className="num mt-0.5 font-mono text-xs text-sev-low">{finding.expected_value}</div>
        </div>
      </div>

      {/* Impact and recommendation come from the LLM narrative, which
          deterministic rules do not have. Saying the rule carries none is
          honest; an empty paragraph would look like a rendering failure. */}
      <div>
        <div className="section-label">Impact</div>
        <p className="mt-1 text-sm text-muted-foreground">
          {finding.impact ?? "This rule carries no written impact analysis."}
        </p>
      </div>

      <div>
        <div className="section-label">Recommendation</div>
        <p className="mt-1 text-sm">
          {finding.recommendation ?? (
            <span className="text-muted-foreground">
              No remediation text is attached to this rule. The expected value above is the
              target state.
            </span>
          )}
        </p>
      </div>

      <div>
        <div className="section-label mb-1.5">Evidence</div>
        {/* Null for a finding recovered from the knowledge base rather than
            observed in a scan. Rendering an empty evidence block would imply
            a file was read. */}
        {finding.evidence ? (
          <EvidenceBlock evidence={finding.evidence} />
        ) : (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            No observation recorded.
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className="section-label">CVE references</div>
          {finding.cves.length ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {finding.cves.map((c) => (
                <a
                  key={c}
                  href={`https://nvd.nist.gov/vuln/detail/${c}`}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md border border-border px-2 py-0.5 font-mono text-[11px] text-accent hover:bg-panel-alt"
                >
                  {c}
                </a>
              ))}
            </div>
          ) : (
            <p className="mt-1.5 text-xs text-muted-foreground">
              No CVE — configuration weakness, not a software defect.
            </p>
          )}
        </div>
        <div>
          <div className="section-label">Attack chains</div>
          {finding.in_chains.length ? (
            <div className="mt-1.5 space-y-1.5">
              {finding.in_chains.map((id) => {
                const chain = chainById(id);
                return (
                  <Link
                    key={id}
                    to="/chains"
                    hash={id}
                    className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-panel-alt"
                  >
                    <ShieldAlert
                      className="size-3.5 shrink-0"
                      style={{ color: severityVar(chain?.severity ?? null) }}
                    />
                    <span className="truncate">{chain?.title ?? id}</span>
                    <span
                      className="num ml-auto font-semibold"
                      style={{ color: severityVar(chain?.severity ?? null) }}
                    >
                      {chain ? chain.score.toFixed(1) : "—"}
                    </span>
                  </Link>
                );
              })}
            </div>
          ) : (
            <p className="mt-1.5 text-xs text-muted-foreground">
              Not part of any active attack chain.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function FindingRow({
  finding,
  onSelect,
  selected,
}: {
  finding: Finding;
  onSelect: () => void;
  selected?: boolean;
}) {
  const meta = DIMENSION_META[finding.dimension];
  return (
    <tr
      onClick={onSelect}
      className={`cursor-pointer border-b border-border last:border-0 transition-colors hover:bg-panel-alt ${
        selected ? "bg-panel-alt" : ""
      }`}
    >
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <TechIcon iconKey={finding.target} size="sm" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{finding.title ?? finding.identifier}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">
              {finding.target_label} · {finding.identifier}
            </div>
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap px-4 py-2.5">
        <DimensionChip id={finding.dimension} label={meta.short} />
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-right">
        <div className="flex items-center justify-end gap-2">
          <Score value={finding.score} severity={finding.severity} size="sm" />
          <SeverityBadge severity={finding.severity} />
        </div>
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-center font-mono text-[11px] text-muted-foreground">
        {finding.cves.length ? finding.cves[0] : "—"}
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-center font-mono text-[11px] text-muted-foreground">
        {finding.in_chains.length ? `${finding.in_chains.length} chain(s)` : "—"}
      </td>
    </tr>
  );
}
