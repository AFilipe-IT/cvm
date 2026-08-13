import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useState } from "react";
import { History, PlayCircle } from "lucide-react";

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
  useInvalidateAfterJob,
  useJobs,
  useStartBuild,
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

function BuildPage() {
  const [benchmark, setBenchmark] = useState("");
  const [target, setTarget] = useState<"apache-httpd" | "nginx">("apache-httpd");
  const [model, setModel] = useState("qwen2.5:14b");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [dryRun, setDryRun] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | undefined>();

  const startBuild = useStartBuild();
  const { data: jobs, isLoading, refetch } = useJobs("build");
  const invalidateAfterJob = useInvalidateAfterJob();

  const handleFinished = useCallback(() => {
    invalidateAfterJob();
    void refetch();
  }, [invalidateAfterJob, refetch]);

  function handleStart() {
    startBuild.mutate(
      { benchmark, target, model, ollama_url: ollamaUrl, dry_run: dryRun },
      { onSuccess: (res) => setActiveJobId(res.job_id) },
    );
  }

  return (
    <AppShell
      title="Build"
      subtitle="Populate the knowledge base from a benchmark using a local LLM — the same pipeline as `caspar build`."
    >
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel className="xl:col-span-5">
          <PanelHeader
            title="New build"
            hint="Runs server-side; a full LLM build can take over an hour"
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

              <Field label="LLM model" htmlFor="build-model">
                <TextInput
                  id="build-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </Field>
            </div>

            <Field label="Ollama URL" htmlFor="build-ollama">
              <TextInput
                id="build-ollama"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
              />
            </Field>

            <CheckRow checked={dryRun} onChange={setDryRun}>
              Dry run — extract and score without writing to the database
            </CheckRow>

            <FormError error={startBuild.error} />

            <Button
              variant="primary"
              icon={<PlayCircle className="size-4" />}
              onClick={handleStart}
              disabled={!benchmark || startBuild.isPending}
            >
              {startBuild.isPending ? "Starting…" : "Start build"}
            </Button>
          </div>
        </Panel>

        <Panel className="xl:col-span-7">
          <PanelHeader title="Build output" hint="Streams while the job runs" />
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
            hint="Select a past build to re-read its log"
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
