import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useState } from "react";
import { Download, Package, Puzzle } from "lucide-react";

import { AppShell } from "@/components/cvm/AppShell";
import { JobConsole } from "@/components/cvm/JobConsole";
import {
  Button,
  CheckRow,
  Field,
  FormError,
  Tabs,
  TextInput,
} from "@/components/cvm/forms";
import {
  EmptyState,
  Panel,
  PanelHeader,
  Skeleton,
  TechIcon,
} from "@/components/cvm/primitives";
import { ErrorState } from "@/components/cvm/states";
import {
  useInstallPlugin,
  useInvalidateAfterJob,
  usePlugins,
} from "@/lib/cvm/jobs";

export const Route = createFileRoute("/plugins")({
  head: () => ({ meta: [{ title: "Plugins — CVM" }] }),
  component: PluginsPage,
});

type Tab = "installed" | "available" | "manual";

function PluginsPage() {
  const [tab, setTab] = useState<Tab>("installed");
  const [activeJobId, setActiveJobId] = useState<string | undefined>();
  const [source, setSource] = useState("");
  const [manual, setManual] = useState("");
  const [model, setModel] = useState("qwen2.5:14b");
  const [noLlm, setNoLlm] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const { data, isLoading, error, refetch } = usePlugins();
  // Normalised once rather than `data?.installed ?? []` scattered through the
  // component: an older server, or a serialised error, can answer without the
  // lists, and `.length` of undefined would take the page down.
  const installed = data?.installed ?? [];
  const available = data?.available ?? [];

  const installPlugin = useInstallPlugin();
  const invalidateAfterJob = useInvalidateAfterJob();

  const handleFinished = useCallback(() => {
    invalidateAfterJob();
    void refetch();
  }, [invalidateAfterJob, refetch]);

  function install(params: {
    source: string;
    manual?: string;
    no_llm?: boolean;
    dry_run?: boolean;
  }) {
    installPlugin.mutate(
      { model, ...params },
      { onSuccess: (res) => setActiveJobId(res.job_id) },
    );
  }

  return (
    <AppShell
      title="Plugins"
      subtitle="The technologies CVM can assess — installed from the catalog or from a local benchmark."
    >
      <div className="space-y-4">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            {
              id: "installed",
              label: `Installed${data ? ` (${installed.length})` : ""}`,
            },
            {
              id: "available",
              label: `Available${data ? ` (${available.length})` : ""}`,
            },
            { id: "manual", label: "From benchmark file" },
          ]}
        />

        {error ? <ErrorState error={error} /> : null}

        {tab === "installed" && !error ? (
          <Panel>
            <PanelHeader
              title="Installed plugins"
            />
            <div className="p-4">
              {isLoading ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-24" />
                  ))}
                </div>
              ) : installed.length ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {installed.map((p) => (
                    <div
                      key={p.name}
                      className="rounded-lg border border-border bg-panel-alt/60 p-3"
                    >
                      {/* The same glyph the technology carries everywhere else
                          in the console. Without it a dozen cards of plain text
                          read identically and the name has to be read to tell
                          them apart. */}
                      <div className="flex items-center gap-2.5">
                        <TechIcon iconKey={p.name} size="sm" />
                        <span className="truncate text-sm font-medium">
                          {p.display_name}
                        </span>
                      </div>
                      <p className="mt-2 truncate text-[11px] text-muted-foreground">
                        {p.benchmark_source}
                      </p>
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <code className="truncate font-mono text-[11px] text-muted-foreground">
                          {p.name}
                        </code>
                        <span className="num shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px]">
                          v{p.version}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={Puzzle}
                  title="No plugins installed"
                  description="Nothing can be assessed until a plugin is installed. Try the catalog tab."
                />
              )}
            </div>
          </Panel>
        ) : null}

        {tab === "available" && !error ? (
          <Panel>
            <PanelHeader
              title="Available from catalog"
            />
            <div className="p-4">
              {isLoading ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-24" />
                  ))}
                </div>
              ) : available.length ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {available.map((p) => (
                    <div
                      key={p.service}
                      className="rounded-lg border border-border bg-panel-alt/60 p-3"
                    >
                      <div className="flex items-center gap-2.5">
                        <TechIcon iconKey={p.service} size="sm" />
                        <span className="truncate text-sm font-medium">
                          {p.service_name}
                        </span>
                      </div>
                      <p className="mt-2 truncate text-[11px] text-muted-foreground">
                        {p.sources.map((s) => s.type).filter(Boolean).join(", ") ||
                          "no source"}
                      </p>
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <code className="truncate font-mono text-[11px] text-muted-foreground">
                          {p.service}
                        </code>
                        <Button
                          icon={<Download className="size-3.5" />}
                          disabled={installPlugin.isPending}
                          onClick={() => install({ source: p.service })}
                        >
                          Install
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={Package}
                  title="Everything in the catalog is installed"
                  description="Use the benchmark-file tab to add a technology the catalog does not cover."
                />
              )}
            </div>
          </Panel>
        ) : null}

        {tab === "manual" ? (
          <Panel>
            <PanelHeader
              title="Install from a benchmark file"
            />
            <div className="max-w-2xl space-y-4 p-4">
              <Field label="Benchmark path" htmlFor="plugin-source">
                <TextInput
                  id="plugin-source"
                  placeholder="/benchmarks/CIS_nginx.pdf"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                />
              </Field>

              <Field
                label="Service manual (optional)"
                htmlFor="plugin-manual"
                
              >
                <TextInput
                  id="plugin-manual"
                  placeholder="https://nginx.org/en/docs/dirindex.pdf"
                  value={manual}
                  onChange={(e) => setManual(e.target.value)}
                />
              </Field>

              <Field label="LLM model" htmlFor="plugin-model">
                <TextInput
                  id="plugin-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </Field>

              <CheckRow checked={noLlm} onChange={setNoLlm}>
                Heuristic extraction only — skip the LLM for ambiguous controls
              </CheckRow>
              <CheckRow checked={dryRun} onChange={setDryRun}>
                Dry run — show the extracted spec without installing
              </CheckRow>

              <FormError error={installPlugin.error} />

              <Button
                variant="primary"
                icon={<Download className="size-4" />}
                disabled={!source || installPlugin.isPending}
                onClick={() =>
                  install({
                    source,
                    ...(manual ? { manual } : {}),
                    no_llm: noLlm,
                    dry_run: dryRun,
                  })
                }
              >
                {installPlugin.isPending ? "Starting…" : "Install plugin"}
              </Button>
            </div>
          </Panel>
        ) : null}

        <Panel>
          <PanelHeader title="Install output" hint="Streams while a job runs" />
          <div className="p-4">
            <JobConsole
              jobId={activeJobId}
              onFinished={handleFinished}
              placeholder="Install a plugin to stream its output here."
            />
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
