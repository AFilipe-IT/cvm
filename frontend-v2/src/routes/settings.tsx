import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  Copy,
  Lock,
  Plus,
  ShieldOff,
  Stethoscope,
  Trash2,
  Wrench,
} from "lucide-react";

import { AppShell } from "@/components/cvm/AppShell";
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
  Explainer,
  Panel,
  PanelHeader,
  Skeleton,
} from "@/components/cvm/primitives";
import { ScoreScaleLegend } from "@/components/cvm/dimensions";
import { usePosture } from "@/lib/cvm/api";
import { ErrorState, LoadingState } from "@/components/cvm/states";
import {
  useCreateSuppression,
  useDeleteSuppression,
  useDoctor,
  useFixPreview,
  usePromoteStats,
  useServerSettings,
  useSuppressions,
} from "@/lib/cvm/manage";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — CVM" },
      {
        name: "description",
        content:
          "Console theme, API access, server configuration, finding exceptions and fix previews for CVM.",
      },
      { property: "og:title", content: "Settings — CVM" },
      { property: "og:description", content: "Theme, API endpoint and knowledge base manifest." },
    ],
  }),
  component: SettingsPage,
});

type Tab = "console" | "server" | "risks" | "remediate";

function SettingsPage() {
  const [tab, setTab] = useState<Tab>("console");

  return (
    <AppShell
      title="Settings"
      subtitle="Console preferences, server configuration and the management surface"
    >
      <div className="space-y-4">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "console", label: "Console" },
            { id: "server", label: "Server" },
            // Named for what the operator does, not for the mechanism. The
            // previous "Accepted risks" / "Remediation" read as report
            // sections — nouns describing something to look at — when both are
            // in fact actions taken against a config.
            { id: "risks", label: "Exceptions" },
            { id: "remediate", label: "Fix preview" },
          ]}
        />

        {tab === "console" ? <ConsoleTab /> : null}
        {tab === "server" ? <ServerTab /> : null}
        {tab === "risks" ? <RisksTab /> : null}
        {tab === "remediate" ? <RemediateTab /> : null}
      </div>
    </AppShell>
  );
}

// ── console ────────────────────────────────────────────────────────────

function ConsoleTab() {
  // Only the manifest panel needs the API. Theme and endpoint reference are
  // client-side, and they are exactly what an operator wants to reach when the
  // backend is the thing that is not answering.
  const { data: posture, isLoading, error } = usePosture();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);
  const apply = (next: "light" | "dark") => {
    setTheme(next);
    localStorage.setItem("cvm-theme", next);
    document.documentElement.classList.toggle("dark", next === "dark");
  };

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel>
        <PanelHeader title="Appearance" hint="Theme is applied at token level" />
        <div className="px-5 py-4">
          <div className="grid grid-cols-2 gap-2">
            {(["light", "dark"] as const).map((t) => (
              <button
                key={t}
                onClick={() => apply(t)}
                className={`rounded-lg border p-3 text-left text-sm capitalize ${
                  theme === t
                    ? "border-accent bg-accent/8 font-medium"
                    : "border-border hover:bg-panel-alt"
                }`}
              >
                {t} theme
              </button>
            ))}
          </div>
          <div className="mt-4">
            <div className="section-label mb-2">Score scale</div>
            <ScoreScaleLegend />
            {/* The legend shows the bands; what it cannot show is that 7.4 is
                not 74%. That misreading is the only thing worth a sentence. */}
            <p className="mt-2 text-xs text-muted-foreground">
              Risk, not a percentage or a grade.
            </p>
          </div>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="API" />
        <div className="space-y-3 px-5 py-4">
          {[
            "GET /api/v1/posture",
            "GET /api/v1/findings",
            "GET /api/v1/chains",
            "GET /api/v1/targets",
          ].map((e) => (
            <div
              key={e}
              className="flex items-center justify-between rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
            >
              <code className="font-mono text-xs">{e}</code>
              <button
                className="text-muted-foreground hover:text-foreground"
                aria-label={`Copy ${e}`}
                onClick={() => navigator.clipboard?.writeText(e.split(" ")[1] ?? "")}
              >
                <Copy className="size-3.5" />
              </button>
            </div>
          ))}
          {/* The engine has no bearer-token scheme, which the mock claimed.
              Auth is off unless CASPAR_API_KEY is set, and it is an X-API-Key
              header on write routes only. Not restated in prose here: the
              Server tab renders `api_key_required` as a field, which is the
              same fact as live data instead of a paragraph. */}
        </div>
      </Panel>

      <Panel className="xl:col-span-2">
        <PanelHeader
          title="Knowledge base"
          action={
            <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Lock className="size-3" /> immutable
            </span>
          }
        />
        {isLoading ? (
          <LoadingState label="Loading manifest…" />
        ) : error || !posture ? (
          <ErrorState error={error} />
        ) : (
          <dl className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-3">
            {[
              ["Engine version", `CVM ${posture.manifest.cvm_version ?? "unknown"}`],
              // Null when the aggregated scans were run against different
              // knowledge bases — stated rather than shown as a blank cell.
              ["Knowledge base sha256", posture.manifest.db_sha256 ?? "mixed across scans"],
              ["Scoring model", `v${posture.scoring_model.version}`],
              ["Aggregation", posture.scoring_model.aggregation],
              ["Missing dimension policy", posture.scoring_model.missing_dimension_policy],
              ["Rules", `${posture.totals.rules_evaluated} evaluated`],
            ].map(([k, v]) => (
              <div key={k} className="bg-panel px-5 py-3">
                <dt className="section-label">{k}</dt>
                <dd className="num mt-1 font-mono text-xs">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </Panel>
    </div>
  );
}

// ── server ─────────────────────────────────────────────────────────────

function ServerTab() {
  const { data: settings, isLoading, error } = useServerSettings();
  const [strict, setStrict] = useState(false);
  const { data: doctor, isLoading: doctorLoading } = useDoctor(strict);
  const { data: promote } = usePromoteStats();

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel>
        <PanelHeader
          title="Effective configuration"
          hint="How this server was launched"
          action={
            <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Lock className="size-3" /> read-only
            </span>
          }
        />
        <div className="px-5 py-4">
          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          ) : error || !settings ? (
            <ErrorState error={error} />
          ) : (
            <>
              <dl className="space-y-2">
                {[
                  ["Engine version", settings.caspar_version],
                  ["Database", settings.db_path],
                  ["Plugins directory", settings.plugins_dir ?? "default"],
                  ["Data directory", settings.data_dir ?? "default"],
                  [
                    "Write authentication",
                    settings.api_key_required ? "X-API-Key required" : "open",
                  ],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-3">
                    <dt className="section-label shrink-0">{k}</dt>
                    <dd className="truncate font-mono text-xs">{v}</dd>
                  </div>
                ))}
              </dl>
              {/* Read-only by design, not an oversight worth a bug report:
                  the API's auth is a no-op unless CASPAR_API_KEY is set, so
                  editing server config over HTTP is deliberately not offered.
                  See schemas_manage.py. Not restated here — the panel header
                  already carries a "read-only" badge. */}
              <div className="mt-3">
                <div className="section-label mb-1.5">
                  Registered plugins · {settings.registered_plugins.length}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {settings.registered_plugins.map((p) => (
                    <code
                      key={p}
                      className="rounded-md border border-border px-2 py-0.5 font-mono text-[11px]"
                    >
                      {p}
                    </code>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Database integrity" hint="The same check as `caspar doctor`" />
        <div className="px-5 py-4">
          <CheckRow checked={strict} onChange={setStrict}>
            Strict — treat warnings as errors
          </CheckRow>

          {doctorLoading || !doctor ? (
            <div className="mt-3 space-y-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          ) : (
            <>
              {/* The verdict lives in these fields, never in the HTTP status: a
                  report full of findings is a *successful* check. */}
              <div className="mt-3 flex items-center gap-2">
                <span
                  className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                  style={{
                    color: doctor.healthy ? "var(--sev-low)" : "var(--sev-medium)",
                    backgroundColor: `color-mix(in oklab, ${
                      doctor.healthy ? "var(--sev-low)" : "var(--sev-medium)"
                    } 14%, transparent)`,
                  }}
                >
                  {doctor.healthy ? "healthy" : "attention"}
                </span>
                <span className="num text-xs text-muted-foreground">
                  {doctor.errors} error{doctor.errors === 1 ? "" : "s"} · {doctor.warnings}{" "}
                  warning{doctor.warnings === 1 ? "" : "s"}
                </span>
              </div>

              {doctor.findings.length ? (
                <ul className="mt-3 space-y-2">
                  {doctor.findings.map((f, i) => (
                    <li
                      key={`${f.category}-${i}`}
                      className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="section-label">{f.severity}</span>
                        <code className="font-mono text-[11px] text-muted-foreground">
                          {f.category}
                        </code>
                      </div>
                      <p className="mt-1 text-xs">{f.message}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-xs text-muted-foreground">
                  No integrity problems reported.
                </p>
              )}
            </>
          )}
        </div>
      </Panel>

      <Panel className="xl:col-span-2">
        <PanelHeader
          title="Rule promotion"
        />
        <div className="px-5 py-4">
          {promote && promote.length ? (
            <div className="scroll-x">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border">
                    {["Target", "Rules", "Promoted", "Needs review"].map((h) => (
                      <th key={h} className="section-label px-3 py-2 font-semibold">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {promote.map((r) => (
                    <tr key={r.target} className="border-b border-border last:border-0">
                      <td className="px-3 py-2 font-mono text-xs">{r.target}</td>
                      <td className="num px-3 py-2 text-xs">{r.rules}</td>
                      <td className="num px-3 py-2 text-xs">{r.promoted}</td>
                      <td className="num px-3 py-2 text-xs">{r.needs_review}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="space-y-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}

// ── exceptions (suppressions) ──────────────────────────────────────────

function RisksTab() {
  const [file, setFile] = useState("");
  const [applied, setApplied] = useState("");
  const { data: items, isLoading, error } = useSuppressions(applied);
  const create = useCreateSuppression(applied);
  const remove = useDeleteSuppression(applied);

  const [directive, setDirective] = useState("");
  const [reason, setReason] = useState("");
  const [badValue, setBadValue] = useState("");

  return (
    <div className="space-y-4">
      <Explainer icon={ShieldOff} title="Exceptions — findings you have decided not to fix">
        <p>
          Some findings are real but will not be acted on: a compensating control
          already covers them, or the setting is required by the application. An
          exception hides such a finding from future assessments and from the
          score, so the remaining findings are the ones that still need work.
        </p>
        <p>
          Every exception records a written reason and lives in a file on the
          server, which is what makes the decision auditable rather than
          invisible. This is the same list <code className="font-mono">caspar
          suppress</code> manages, and a scan applies it with{" "}
          <code className="font-mono">--suppress-file</code>. Nothing is deleted:
          removing an exception here brings the finding straight back.
        </p>
      </Explainer>

      <div className="grid gap-4 xl:grid-cols-12">
      <Panel className="xl:col-span-5">
        <PanelHeader title="Suppression file" hint="A path on the server" />
        <div className="space-y-4 p-4">
          {/* The CLI defaults this to the process cwd; a server has no
              meaningful cwd, so the path is always explicit here. */}
          <Field
            label="File path"
            htmlFor="supp-file"
            hint="Name a file to list accepted risks"
          >
            <TextInput
              id="supp-file"
              placeholder="/etc/caspar/.caspar-suppress.json"
              value={file}
              onChange={(e) => setFile(e.target.value)}
            />
          </Field>
          <Button variant="primary" disabled={!file} onClick={() => setApplied(file)}>
            Load
          </Button>

          {applied ? (
            <>
              <div className="border-t border-border pt-4">
                <div className="section-label mb-2">Accept a new risk</div>
                <div className="space-y-3">
                  <Field label="Directive" htmlFor="supp-directive">
                    <TextInput
                      id="supp-directive"
                      placeholder="server_tokens"
                      value={directive}
                      onChange={(e) => setDirective(e.target.value)}
                    />
                  </Field>
                  <Field label="Insecure value (optional)" htmlFor="supp-value">
                    <TextInput
                      id="supp-value"
                      value={badValue}
                      onChange={(e) => setBadValue(e.target.value)}
                    />
                  </Field>
                  {/* Mandatory server-side and mandatory here: accepting a risk
                      with no justification is precisely what this feature
                      exists to prevent. */}
                  <Field
                    label="Reason"
                    htmlFor="supp-reason"
                    hint="Required"
                  >
                    <TextInput
                      id="supp-reason"
                      placeholder="Compensating control: fronted by WAF"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </Field>

                  <FormError error={create.error} />

                  <Button
                    icon={<Plus className="size-4" />}
                    disabled={!directive || !reason.trim() || create.isPending}
                    onClick={() =>
                      create.mutate(
                        {
                          directive,
                          reason,
                          ...(badValue ? { bad_value: badValue } : {}),
                        },
                        {
                          onSuccess: () => {
                            setDirective("");
                            setReason("");
                            setBadValue("");
                          },
                        },
                      )
                    }
                  >
                    {create.isPending ? "Accepting…" : "Accept risk"}
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </Panel>

      <Panel className="xl:col-span-7">
        <PanelHeader
          title="Accepted risks"
        />
        <div className="p-4">
          {!applied ? (
            <EmptyState
              icon={ShieldOff}
              title="No suppression file loaded"
              description="Name a file on the server to see which risks have been accepted."
            />
          ) : error ? (
            <ErrorState error={error} />
          ) : isLoading ? (
            <div className="space-y-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : items && items.length ? (
            <ul className="space-y-2">
              {items.map((s) => (
                <li
                  key={s.directive}
                  className="flex items-start justify-between gap-3 rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
                >
                  <div className="min-w-0">
                    <code className="font-mono text-xs font-semibold">{s.directive}</code>
                    {s.bad_value ? (
                      <code className="ml-2 font-mono text-[11px] text-muted-foreground">
                        {s.bad_value}
                      </code>
                    ) : null}
                    <p className="mt-1 text-xs text-muted-foreground">{s.reason}</p>
                    {s.date ? (
                      <p className="mt-0.5 text-[11px] text-muted-foreground">{s.date}</p>
                    ) : null}
                  </div>
                  <button
                    onClick={() => remove.mutate(s.directive)}
                    aria-label={`Withdraw acceptance of ${s.directive}`}
                    className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:text-sev-critical"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={ShieldOff}
              title="No exceptions in this file"
              description="Every finding counts against the score."
            />
          )}
        </div>
      </Panel>
      </div>
    </div>
  );
}

// ── fix preview (caspar fix --dry-run) ─────────────────────────────────

function RemediateTab() {
  const [inputPath, setInputPath] = useState("");
  const [live, setLive] = useState(false);
  const preview = useFixPreview();
  const result = preview.data;

  return (
    <div className="space-y-4">
      <Explainer icon={Wrench} title="Fix preview — the corrected config, before you apply it">
        <p>
          Name a configuration file on the server and CVM shows the exact lines it
          would change to clear the findings it can fix automatically, alongside
          the ones it cannot. Nothing is written: this is a preview, and the file
          on disk is left untouched.
        </p>
        <p>
          It is the read-only half of <code className="font-mono">caspar fix</code>.
          Writing the change is deliberately left to the CLI —{" "}
          <code className="font-mono">caspar fix --in-place</code> — so editing a
          production config is always a decision taken on the host, never a button
          in a browser.
        </p>
      </Explainer>

      <div className="grid gap-4 xl:grid-cols-12">
      <Panel className="xl:col-span-4">
        <PanelHeader title="Preview remediation" hint="Nothing is written" />
        <div className="space-y-4 p-4">
          <Field label="Config path" htmlFor="fix-path">
            <TextInput
              id="fix-path"
              placeholder="/etc/nginx/nginx.conf"
              value={inputPath}
              onChange={(e) => setInputPath(e.target.value)}
            />
          </Field>

          <CheckRow checked={live} onChange={setLive}>
            Live service — read the installed configuration
          </CheckRow>

          {/* Stated up front, not discovered after clicking: this is one of the
              two deliberate CLI asymmetries, and an operator expecting the fix
              to land needs to know before they rely on it. */}
          <p className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2 text-xs text-muted-foreground">
            Preview only — apply with <code className="font-mono">caspar fix --in-place</code>.
          </p>

          <FormError error={preview.error} />

          <Button
            variant="primary"
            icon={<Wrench className="size-4" />}
            disabled={!inputPath || preview.isPending}
            onClick={() => preview.mutate({ input_path: inputPath, live })}
          >
            {preview.isPending ? "Computing…" : "Preview fix"}
          </Button>
        </div>
      </Panel>

      <Panel className="xl:col-span-8">
        <PanelHeader title="Proposed changes" />
        <div className="p-4">
          {result ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4 text-xs">
                <span className="text-muted-foreground">
                  Target <span className="font-mono">{result.target_name ?? "unknown"}</span>
                </span>
                <span className="num">{result.edits.length} automatic</span>
                <span className="num">{result.manual.length} manual</span>
              </div>

              {result.diff ? (
                <div>
                  <div className="section-label mb-1.5">Diff</div>
                  <pre className="scroll-x rounded-lg border border-border bg-panel-alt/60 p-3 font-mono text-[11px] leading-relaxed">
                    {result.diff}
                  </pre>
                </div>
              ) : null}

              {result.manual.length ? (
                <div>
                  <div className="section-label mb-1.5">Needs a human decision</div>
                  <ul className="space-y-2">
                    {result.manual.map((m, i) => (
                      <li
                        key={`${m.directive}-${i}`}
                        className="rounded-lg border border-border bg-panel-alt/60 px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <code className="font-mono text-xs font-semibold">
                            {m.directive}
                          </code>
                          <span className="num text-xs">{m.score.toFixed(1)}</span>
                        </div>
                        {m.good_value ? (
                          <code className="mt-1 block font-mono text-[11px] text-muted-foreground">
                            → {m.good_value}
                          </code>
                        ) : null}
                        <p className="mt-1 text-xs text-muted-foreground">
                          {m.recommendation || m.reason}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState
              icon={Stethoscope}
              title="No preview computed"
              description="Name a config file to see what CVM would change and what it would leave to you."
            />
          )}
        </div>
      </Panel>
      </div>
    </div>
  );
}
