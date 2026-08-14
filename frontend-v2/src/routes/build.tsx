import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useState } from "react";
import { History, KeyRound, PlayCircle } from "lucide-react";

import { AppShell } from "@/components/cvm/AppShell";
import { JobConsole } from "@/components/cvm/JobConsole";
import {
  Button,
  CheckRow,
  Field,
  FormError,
  Select,
  TextInput,
} from "@/components/cvm/forms";
import {
  EmptyState,
  Panel,
  PanelHeader,
  Skeleton,
  TimeStamp,
} from "@/components/cvm/primitives";
import {
  useBuildProviders,
  useInvalidateAfterJob,
  useJobs,
  useStartBuild,
  type BuildProvider,
  type JobStatus,
} from "@/lib/cvm/jobs";

export const Route = createFileRoute("/build")({
  head: () => ({ meta: [{ title: "Build — CVM" }] }),
  component: BuildPage,
});

const STATUS_COLOR: Record<JobStatus, string> = {
  queued: "var(--text-muted)",
  running: "var(--accent)",
  succeeded: "var(--sev-low)",
  failed: "var(--sev-critical)",
  cancelled: "var(--text-muted)",
};

/**
 * Whether the server holds a key for this engine.
 *
 * It reports the variable's name, never a value — the console has no way to
 * read a key and no business holding one. Fixing a missing key means exporting
 * it where the server runs and restarting it, which is why the hint names the
 * variable rather than offering a field to type it into.
 */
function KeyStatus({ present, env }: { present: boolean; env: string }) {
  return present ? (
    <span className="inline-flex items-center gap-1.5">
      <KeyRound className="size-3" style={{ color: "var(--sev-low)" }} />
      <code className="font-mono">{env}</code> is set on the server.
    </span>
  ) : (
    <span
      className="inline-flex items-center gap-1.5"
      style={{ color: "var(--sev-high)" }}
    >
      <KeyRound className="size-3" />
      No key. Export <code className="font-mono">{env}</code> where the server
      runs, then restart it.
    </span>
  );
}

function BuildPage() {
  const [benchmark, setBenchmark] = useState("");
  const [target, setTarget] = useState<"apache-httpd" | "nginx">("apache-httpd");
  const [provider, setProvider] = useState<BuildProvider>("ollama");
  // Empty means "this provider's usual model", which the server resolves. A
  // pre-filled Ollama tag would silently follow the operator to Claude, where
  // it means nothing.
  const [model, setModel] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [dryRun, setDryRun] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | undefined>();

  const startBuild = useStartBuild();
  const { data: providers } = useBuildProviders();
  const { data: jobs, isLoading, refetch } = useJobs("build");
  const invalidateAfterJob = useInvalidateAfterJob();

  const chosen = providers?.find((p) => p.id === provider);
  // A paid provider with no key on the server cannot possibly succeed, so the
  // button says so instead of letting the operator start a job that dies on
  // its first call — which, on a real benchmark, is minutes in.
  const keyMissing = Boolean(chosen && !chosen.key_present);

  const handleFinished = useCallback(() => {
    invalidateAfterJob();
    void refetch();
  }, [invalidateAfterJob, refetch]);

  function handleStart() {
    startBuild.mutate(
      {
        benchmark,
        target,
        provider,
        ...(model.trim() ? { model: model.trim() } : {}),
        ollama_url: ollamaUrl,
        dry_run: dryRun,
      },
      { onSuccess: (res) => setActiveJobId(res.job_id) },
    );
  }

  return (
    <AppShell
      title="Build"
      subtitle="Populate the knowledge base from a benchmark, using a local or paid model — the same pipeline as `caspar build`."
    >
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="xl:col-span-5">
          <PanelHeader
            title="New build"
          />
          <div className="space-y-4 p-4">
            <Field
              label="Benchmark path"
              htmlFor="build-benchmark"
              hint={
                <>
                  A path on the server, as passed to{" "}
                  <code className="font-mono">caspar build --benchmark</code>.
                </>
              }
            >
              <TextInput
                id="build-benchmark"
                placeholder="plugins/apache_httpd/Benchmark.pdf"
                value={benchmark}
                onChange={(e) => setBenchmark(e.target.value)}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Target" htmlFor="build-target">
                <Select
                  id="build-target"
                  value={target}
                  onChange={(e) =>
                    setTarget(e.target.value as "apache-httpd" | "nginx")
                  }
                >
                  <option value="apache-httpd">apache-httpd</option>
                  <option value="nginx">nginx</option>
                </Select>
              </Field>

              <Field
                label="Engine"
                htmlFor="build-provider"
                hint={
                  chosen?.requires_key ? (
                    <KeyStatus present={chosen.key_present} env={chosen.key_env} />
                  ) : (
                    "Runs on this machine. No key, no cost."
                  )
                }
              >
                <Select
                  id="build-provider"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value as BuildProvider)}
                >
                  {(providers ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            <Field
              label="Model"
              htmlFor="build-model"
              hint={
                chosen
                  ? `Leave empty for ${chosen.default_model}.`
                  : "Leave empty for this engine's usual model."
              }
            >
              <TextInput
                id="build-model"
                value={model}
                placeholder={chosen?.default_model ?? ""}
                onChange={(e) => setModel(e.target.value)}
              />
            </Field>

            {provider === "ollama" ? (
              <Field label="Ollama URL" htmlFor="build-ollama">
                <TextInput
                  id="build-ollama"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                />
              </Field>
            ) : null}

            <CheckRow checked={dryRun} onChange={setDryRun}>
              Dry run — extract and score without writing to the database
            </CheckRow>

            <FormError error={startBuild.error} />

            <Button
              variant="primary"
              icon={<PlayCircle className="size-4" />}
              onClick={handleStart}
              disabled={!benchmark || keyMissing || startBuild.isPending}
            >
              {startBuild.isPending ? "Starting…" : "Start build"}
            </Button>
          </div>
        </Panel>

        <Panel className="xl:col-span-7">
          <PanelHeader title="Build output" />
          <div className="p-4">
            <JobConsole
              jobId={activeJobId}
              onFinished={handleFinished}
              placeholder="Start a build to stream its output here."
            />
          </div>
        </Panel>

        <Panel className="xl:col-span-12">
          <PanelHeader
            title="Build history"
          />
          <div className="p-4">
            {isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-9" />
                ))}
              </div>
            ) : jobs && jobs.length ? (
              <div className="divide-y divide-border">
                {jobs.map((job) => (
                  <button
                    key={job.id}
                    onClick={() => setActiveJobId(job.id)}
                    className={`flex w-full items-center gap-3 px-2 py-2.5 text-left text-sm transition-colors hover:bg-panel-alt ${
                      job.id === activeJobId ? "bg-panel-alt" : ""
                    }`}
                  >
                    <code className="font-mono text-[11px] text-muted-foreground">
                      {job.id.slice(0, 8)}
                    </code>
                    <TimeStamp iso={job.created_at} className="flex-1" />
                    <span
                      className="shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold"
                      style={{
                        color: STATUS_COLOR[job.status],
                        backgroundColor: `color-mix(in oklab, ${STATUS_COLOR[job.status]} 14%, transparent)`,
                      }}
                    >
                      {job.status}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={History}
                title="No builds run yet"
                description="A build extracts rules from a benchmark into the knowledge base."
              />
            )}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
