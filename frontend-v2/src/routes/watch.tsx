import { createFileRoute } from "@tanstack/react-router";
import { Activity, FilePen, PlusCircle, RefreshCcw, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/cvm/AppShell";
import {
  Delta,
  Panel,
  PanelHeader,
  Score,
  SeverityBadge,
  Sparkline,
  TechIcon,
  TimeStamp,
} from "@/components/cvm/primitives";
import { useWatchEvents, useWatchSessions } from "@/lib/cvm/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/cvm/states";
import { severityVar } from "@/lib/cvm/ui";

export const Route = createFileRoute("/watch")({
  head: () => ({
    meta: [
      { title: "Watch — Continuous Monitoring — CVM" },
      {
        name: "description",
        content:
          "Live monitoring sessions that re-assess targets when configuration changes, with an event stream and score sparklines.",
      },
      { property: "og:title", content: "Watch — Continuous Monitoring — CVM" },
      { property: "og:description", content: "Live and stale sessions, change-triggered re-assessment." },
    ],
  }),
  component: WatchPage,
});

const EVENT_ICON = {
  config_change: FilePen,
  reassessment: RefreshCcw,
  new_finding: PlusCircle,
  resolved: ShieldCheck,
} as const;

const stateStyle = (s: "live" | "stale" | "paused") =>
  s === "live"
    ? { color: "var(--sev-low)", label: "Live" }
    : s === "stale"
      ? { color: "var(--sev-medium)", label: "Stale" }
      : { color: "var(--sev-none)", label: "Paused" };

function WatchPage() {
  const sessionsQuery = useWatchSessions();
  const eventsQuery = useWatchEvents();
  const sessions = sessionsQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  return (
    <AppShell
      title="Watch"
      subtitle="Continuous monitoring — targets are re-assessed when their configuration changes"
    >
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="space-y-3 xl:col-span-7">
          <h2 className="text-sm font-semibold tracking-tight">
            Sessions · {sessions.filter((s) => s.state === "live").length} live
          </h2>
          {sessionsQuery.isLoading ? (
            <Panel>
              <LoadingState label="Loading watch sessions…" />
            </Panel>
          ) : sessionsQuery.error ? (
            <Panel>
              <ErrorState error={sessionsQuery.error} />
            </Panel>
          ) : sessions.length === 0 ? (
            <Panel>
              <EmptyState
                title="No watch sessions"
                hint="Start one with `caspar watch <target>`. A session keeps re-assessing its target and records every change here."
                icon={<Activity className="size-5" />}
              />
            </Panel>
          ) : null}
          {sessions.map((s) => {
            const st = stateStyle(s.state);
            return (
              <Panel key={s.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                <TechIcon iconKey={s.icon_key} size="lg" />
                <div className="min-w-[140px] flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{s.target_label}</span>
                    <span
                      className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium"
                      style={{
                        color: st.color,
                        backgroundColor: `color-mix(in oklab, ${st.color} 14%, transparent)`,
                      }}
                    >
                      <span className="size-1.5 rounded-full" style={{ backgroundColor: st.color }} />
                      {st.label}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{s.interval}</span>
                    <span>·</span>
                    <span>
                      last event <TimeStamp iso={s.last_event_at} />
                    </span>
                  </div>
                </div>
                <Sparkline data={s.sparkline} color={severityVar(s.severity)} />
                <div className="flex items-center gap-2">
                  <Score value={s.score} severity={s.severity} size="md" />
                  <SeverityBadge severity={s.severity} />
                </div>
              </Panel>
            );
          })}
        </div>

        <Panel className="xl:col-span-5">
          <PanelHeader title="Event stream" hint="Configuration changes and their score impact" />
          {eventsQuery.isLoading ? (
            <LoadingState label="Loading events…" />
          ) : eventsQuery.error ? (
            <ErrorState error={eventsQuery.error} />
          ) : events.length === 0 ? (
            <EmptyState
              title="No events recorded"
              hint="Each re-assessment a watch session performs is recorded here with its effect on the score."
              icon={<RefreshCcw className="size-5" />}
            />
          ) : null}
          <ul className="divide-y divide-border">
            {events.map((e) => {
              const Icon = EVENT_ICON[e.kind];
              return (
                <li key={e.id} className="flex items-start gap-3 px-5 py-3">
                  <span className="mt-0.5">
                    <TechIcon iconKey={e.icon_key} size="sm" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Icon className="size-3.5 text-muted-foreground" />
                      <span className="text-xs font-medium">{e.target_label}</span>
                      <span className="section-label">{e.kind.replace("_", " ")}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{e.message}</p>
                    <div className="mt-1 flex items-center gap-3">
                      <TimeStamp iso={e.at} />
                      <Delta value={e.delta} />
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          {/* The mock claimed events were archived after 24h. Nothing archives
              them — every event is a stored assessment and stays queryable. */}
          <div className="flex items-center gap-2 border-t border-border px-5 py-3 text-[11px] text-muted-foreground">
            <Activity className="size-3.5" /> Each event is a stored assessment; the change shown
            is against the one before it.
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
