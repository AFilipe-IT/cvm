import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { FileUp, GitCompareArrows, History, PlayCircle, Trash2 } from "lucide-react";

import { AppShell } from "@/components/cvm/AppShell";
import {
  Button,
  CheckRow,
  Field,
  FormError,
  Select,
  Tabs,
  TextInput,
} from "@/components/cvm/forms";
import {
  Delta,
  EmptyState,
  Panel,
  PanelHeader,
  Score,
  SeverityBadge,
  Skeleton,
  TechIcon,
  TimeStamp,
} from "@/components/cvm/primitives";
import {
  useCompareScans,
  useDeleteScan,
  useRunScan,
  useScanHistory,
  useUploadScan,
  type EnvProfile,
  type ScanResponse,
} from "@/lib/cvm/scans";
import { useTargets } from "@/lib/cvm/api";

export const Route = createFileRoute("/assessment")({
  head: () => ({ meta: [{ title: "Assessment — CVM" }] }),
  component: AssessmentPage,
});

type Tab = "run" | "history" | "compare";

function AssessmentPage() {
  const [tab, setTab] = useState<Tab>("run");
  const [result, setResult] = useState<ScanResponse | null>(null);

  return (
    <AppShell
      title="Assessment"
      subtitle="Run and manage configuration assessments — the same engine as `caspar scan`."
    >
      <div className="space-y-4">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "run", label: "Run" },
            { id: "history", label: "History" },
            { id: "compare", label: "Compare" },
          ]}
        />

        {tab === "run" ? <RunPanel result={result} onResult={setResult} /> : null}
        {tab === "history" ? <HistoryPanel /> : null}
        {tab === "compare" ? <ComparePanel /> : null}
      </div>
    </AppShell>
  );
}

// ── run ────────────────────────────────────────────────────────────────

function RunPanel({
  result,
  onResult,
}: {
  result: ScanResponse | null;
  onResult: (r: ScanResponse) => void;
}) {
  const [mode, setMode] = useState<"path" | "upload" | "live">("path");
  const [inputPath, setInputPath] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [liveTarget, setLiveTarget] = useState("");
  const [host, setHost] = useState("");
  const [envProfile, setEnvProfile] = useState<EnvProfile | "">("");
  const [threshold, setThreshold] = useState("");
  const [assessUnknown, setAssessUnknown] = useState(false);

  const { data: targets } = useTargets();
  const runScan = useRunScan();
  const uploadScan = useUploadScan();

  const pending = runScan.isPending || uploadScan.isPending;
  const error = runScan.error ?? uploadScan.error;

  function submit() {
    const parsedThreshold = threshold === "" ? undefined : Number(threshold);

    if (mode === "upload") {
      if (!file) return;
      uploadScan.mutate(
        {
          file,
          ...(envProfile ? { env_profile: envProfile } : {}),
          ...(host ? { host } : {}),
          ...(parsedThreshold === undefined ? {} : { threshold: parsedThreshold }),
        },
        { onSuccess: onResult },
      );
      return;
    }

    runScan.mutate(
      {
        // `--live` inspects the installed service, so the "path" it is given is
        // the target name rather than a file.
        input_path: mode === "live" ? liveTarget : inputPath,
        ...(mode === "live" ? { live: true } : {}),
        ...(envProfile ? { env_profile: envProfile } : {}),
        ...(host ? { host } : {}),
        ...(parsedThreshold === undefined ? {} : { threshold: parsedThreshold }),
        ...(assessUnknown ? { assess_unknown: true } : {}),
      },
      { onSuccess: onResult },
    );
  }

  const canSubmit =
    mode === "upload" ? Boolean(file) : mode === "live" ? Boolean(liveTarget) : Boolean(inputPath);

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Panel className="xl:col-span-5">
        <PanelHeader title="New assessment" hint="Scans complete in seconds" />
        <div className="space-y-4 p-4">
          <Field label="Source" htmlFor="scan-mode">
            <Select
              id="scan-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as "path" | "upload" | "live")}
            >
              <option value="path">Server path — a config file on this machine</option>
              <option value="upload">Upload — a config file from this browser</option>
              <option value="live">Live service — inspect what is installed</option>
            </Select>
          </Field>

          {mode === "path" ? (
            <Field
              label="Config path"
              htmlFor="scan-path"
              hint="A path on the server, exactly as passed to `caspar scan`."
            >
              <TextInput
                id="scan-path"
                placeholder="/etc/nginx/nginx.conf"
                value={inputPath}
                onChange={(e) => setInputPath(e.target.value)}
              />
            </Field>
          ) : null}

          {mode === "upload" ? (
            <Field
              label="Config file"
              htmlFor="scan-file"
              hint="Staged server-side, then assessed by the same code path as a local scan."
            >
              <input
                id="scan-file"
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full rounded-lg border border-border bg-panel px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-panel-alt file:px-2 file:py-1 file:text-xs"
              />
            </Field>
          ) : null}

          {mode === "live" ? (
            <Field
              label="Target"
              htmlFor="scan-live"
              hint="Reads the installed service's own configuration and version."
            >
              <Select
                id="scan-live"
                value={liveTarget}
                onChange={(e) => setLiveTarget(e.target.value)}
              >
                <option value="">Select a target…</option>
                {(targets ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Host label (optional)" htmlFor="scan-host">
              <TextInput
                id="scan-host"
                placeholder="web01"
                value={host}
                onChange={(e) => setHost(e.target.value)}
              />
            </Field>

            <Field label="Environment (optional)" htmlFor="scan-env">
              <Select
                id="scan-env"
                value={envProfile}
                onChange={(e) => setEnvProfile(e.target.value as EnvProfile | "")}
              >
                <option value="">Not specified</option>
                <option value="production">production</option>
                <option value="internal">internal</option>
                <option value="dev">dev</option>
              </Select>
            </Field>
          </div>

          <Field
            label="Threshold (optional)"
            htmlFor="scan-threshold"
            hint="`caspar scan --threshold` decides an exit code; over HTTP the scan still succeeds, so the verdict comes back as data."
          >
            <TextInput
              id="scan-threshold"
              type="number"
              min={0}
              max={10}
              step={0.1}
              placeholder="7.0"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </Field>

          {mode !== "upload" ? (
            <CheckRow checked={assessUnknown} onChange={setAssessUnknown}>
              Assess directives absent from the knowledge base
            </CheckRow>
          ) : null}

          <FormError error={error} />

          <Button
            variant="primary"
            icon={mode === "upload" ? <FileUp className="size-4" /> : <PlayCircle className="size-4" />}
            onClick={submit}
            disabled={!canSubmit || pending}
          >
            {pending ? "Assessing…" : "Run assessment"}
          </Button>
        </div>
      </Panel>

      <Panel className="xl:col-span-7">
        <PanelHeader title="Result" hint="The assessment just run" />
        <div className="p-4">
          {result ? (
            <ScanResultView result={result} />
          ) : (
            <EmptyState
              icon={PlayCircle}
              title="No assessment run yet"
              description="Run one to see its score, and where it landed against the threshold."
            />
          )}
        </div>
      </Panel>
    </div>
  );
}

function ScanResultView({ result }: { result: ScanResponse }) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <TechIcon iconKey={result.target_name} size="lg" />
          <div className="min-w-0">
            <div className="text-base font-semibold">{result.target_name}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">
              {result.input_path}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <code className="font-mono text-[11px] text-muted-foreground">
                {result.scan_id.slice(0, 8)}
              </code>
              <TimeStamp iso={result.timestamp} />
            </div>
          </div>
        </div>
        <div className="text-right">
          <Score
            value={result.global_temporal_score}
            severity={result.severity}
            size="lg"
          />
          <div className="mt-1">
            <SeverityBadge severity={result.severity} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ["Directives", result.total_directives_scanned],
          ["Findings", result.total_issues_found],
          ["Chains", result.total_chains_detected],
          ["Suppressed", result.suppressed_count],
        ].map(([k, v]) => (
          <div
            key={String(k)}
            className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
          >
            <div className="section-label">{k}</div>
            <div className="num mt-0.5 text-lg font-semibold">{v}</div>
          </div>
        ))}
      </div>

      {/* Only shown when a threshold was actually set: with none, "passed" is
          vacuously true and would read as a verdict nobody asked for. */}
      {result.passed_threshold ? null : (
        <div
          className="rounded-lg border px-3 py-2 text-xs"
          style={{
            color: "var(--sev-critical)",
            borderColor: "color-mix(in oklab, var(--sev-critical) 35%, transparent)",
            backgroundColor: "color-mix(in oklab, var(--sev-critical) 8%, transparent)",
          }}
        >
          This assessment scored above the threshold you set. In CI, `caspar scan`
          would have exited non-zero here.
        </div>
      )}

      {result.detected_version ? (
        <div className="text-xs text-muted-foreground">
          Detected version <span className="num font-mono">{result.detected_version}</span>
        </div>
      ) : null}

      <Link
        to="/findings"
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-panel px-3 py-2 text-sm font-medium hover:bg-panel-alt"
      >
        Open in Findings
      </Link>
    </div>
  );
}

// ── history ────────────────────────────────────────────────────────────

function HistoryPanel() {
  const { data: scans, isLoading } = useScanHistory({ limit: 50 });
  const deleteScan = useDeleteScan();
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <Panel>
      <PanelHeader
        title="Assessment history"
        hint="Every stored assessment, newest first"
      />
      <div className="p-4">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : scans && scans.length ? (
          <div className="scroll-x">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  {["Target", "Source", "Score", "Findings", "When", ""].map((h) => (
                    <th key={h} className="section-label px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={s.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-2">
                        <TechIcon iconKey={s.target_name} size="sm" />
                        <span className="text-xs">{s.target_name}</span>
                      </span>
                    </td>
                    <td className="max-w-[260px] truncate px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                      {s.input_path}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="flex items-center gap-2">
                        <Score
                          value={s.global_temporal_score}
                          severity={s.severity}
                          size="sm"
                        />
                        <SeverityBadge severity={s.severity} />
                      </span>
                    </td>
                    <td className="num px-3 py-2.5 text-xs">{s.total_issues}</td>
                    <td className="px-3 py-2.5">
                      <TimeStamp iso={s.timestamp} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {/* Two-step, because this is irreversible and the row it
                          deletes also feeds the posture and the trends. */}
                      {confirming === s.id ? (
                        <span className="flex items-center justify-end gap-1.5">
                          <Button
                            onClick={() => {
                              deleteScan.mutate(s.id);
                              setConfirming(null);
                            }}
                            className="!px-2 !py-1 !text-xs"
                          >
                            Confirm
                          </Button>
                          <Button
                            onClick={() => setConfirming(null)}
                            className="!px-2 !py-1 !text-xs"
                          >
                            Cancel
                          </Button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setConfirming(s.id)}
                          aria-label={`Delete assessment ${s.id.slice(0, 8)}`}
                          className="inline-flex size-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:text-sev-critical"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={History}
            title="No assessments stored"
            description="Run one from the Run tab; every assessment is kept until deleted."
          />
        )}
      </div>
    </Panel>
  );
}

// ── compare ────────────────────────────────────────────────────────────

function ComparePanel() {
  const { data: scans } = useScanHistory({ limit: 50 });
  const [older, setOlder] = useState("");
  const [newer, setNewer] = useState("");
  const compare = useCompareScans();
  const diff = compare.data;

  const options = scans ?? [];

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Panel className="xl:col-span-4">
        <PanelHeader title="Compare assessments" hint="Older against newer" />
        <div className="space-y-4 p-4">
          {/* Order is load-bearing: run backwards, the diff reports fixes as
              regressions. The labels say which is which rather than leaving it
              to the reader to infer from the ids. */}
          <Field label="Older assessment" htmlFor="cmp-old">
            <Select id="cmp-old" value={older} onChange={(e) => setOlder(e.target.value)}>
              <option value="">Select…</option>
              {options.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.target_name} · {new Date(s.timestamp).toLocaleString()} ·{" "}
                  {s.global_temporal_score.toFixed(1)}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Newer assessment" htmlFor="cmp-new">
            <Select id="cmp-new" value={newer} onChange={(e) => setNewer(e.target.value)}>
              <option value="">Select…</option>
              {options.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.target_name} · {new Date(s.timestamp).toLocaleString()} ·{" "}
                  {s.global_temporal_score.toFixed(1)}
                </option>
              ))}
            </Select>
          </Field>

          <FormError error={compare.error} />

          <Button
            variant="primary"
            icon={<GitCompareArrows className="size-4" />}
            disabled={!older || !newer || older === newer || compare.isPending}
            onClick={() => compare.mutate({ older, newer })}
          >
            {compare.isPending ? "Comparing…" : "Compare"}
          </Button>
        </div>
      </Panel>

      <Panel className="xl:col-span-8">
        <PanelHeader title="Difference" />
        <div className="p-4">
          {diff ? (
            <div className="space-y-4">
              <div className="flex items-center gap-6">
                <div>
                  <div className="section-label">Score</div>
                  <div className="num mt-0.5 text-2xl font-semibold">
                    {diff.old_score.toFixed(1)} → {diff.new_score.toFixed(1)}
                  </div>
                </div>
                <Delta value={diff.score_delta} />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <DiffList
                  title={`Introduced · ${diff.new_issues.length}`}
                  issues={diff.new_issues}
                  color="var(--sev-critical)"
                  empty="No new findings."
                />
                <DiffList
                  title={`Resolved · ${diff.resolved.length}`}
                  issues={diff.resolved}
                  color="var(--sev-low)"
                  empty="Nothing was fixed between these two."
                />
              </div>

              <p className="text-xs text-muted-foreground">
                {diff.unchanged.length} finding
                {diff.unchanged.length === 1 ? "" : "s"} unchanged.
              </p>
            </div>
          ) : (
            <EmptyState
              icon={GitCompareArrows}
              title="Nothing compared yet"
              description="Pick two assessments to see what was fixed and what appeared."
            />
          )}
        </div>
      </Panel>
    </div>
  );
}

function DiffList({
  title,
  issues,
  color,
  empty,
}: {
  title: string;
  issues: { directive: string; temporal_score: number }[];
  color: string;
  empty: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-panel-alt/60 p-3">
      <div className="section-label" style={{ color }}>
        {title}
      </div>
      {issues.length ? (
        <ul className="mt-2 space-y-1">
          {issues.map((i, idx) => (
            <li
              key={`${i.directive}-${idx}`}
              className="flex items-center justify-between gap-2 text-xs"
            >
              <span className="truncate font-mono">{i.directive}</span>
              <span className="num shrink-0 font-semibold" style={{ color }}>
                {i.temporal_score.toFixed(1)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}
