import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Crosshair,
  FileText,
  Gauge,
  Layers,
  ListChecks,
  Menu,
  Moon,
  Settings as SettingsIcon,
  ShieldCheck,
  Sun,
  Waypoints,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { posture } from "@/lib/cvm/data";
import { absoluteTime, relativeTime } from "@/lib/cvm/ui";

const NAV = [
  { to: "/", label: "Overview", icon: Gauge },
  { to: "/dimensions", label: "Dimensions", icon: Layers },
  { to: "/findings", label: "Findings", icon: ListChecks },
  { to: "/chains", label: "Attack Chains", icon: Waypoints },
  { to: "/targets", label: "Targets", icon: Crosshair },
  { to: "/watch", label: "Watch", icon: Activity },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    const stored = localStorage.getItem("cvm-theme");
    const next = stored === "dark" ? "dark" : "light";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
  }, []);
  const toggle = () => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("cvm-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      return next;
    });
  };
  return { theme, toggle };
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <div className="flex h-full flex-col border-r border-border bg-panel">
      <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
        <span className="inline-flex size-9 items-center justify-center rounded-lg bg-accent/12 text-accent">
          <ShieldCheck className="size-5" />
        </span>
        <div>
          <div className="text-base font-semibold leading-none tracking-tight">CVM</div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.09em] text-muted-foreground">
            Configuration Vulnerability Meter
          </div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
        {NAV.map((item) => {
          const active =
            item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent/12 font-medium text-accent"
                  : "text-muted-foreground hover:bg-panel-alt hover:text-foreground",
              )}
            >
              <item.icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="m-3 rounded-lg border border-border bg-panel-alt p-3">
        <div className="section-label">Knowledge base</div>
        <div className="num mt-1.5 text-xl font-semibold">
          {posture.totals.rules_evaluated} rules
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          {posture.totals.targets_assessed} targets · sha256 {posture.manifest.db_sha256}
        </div>
        <Link
          to="/settings"
          className="mt-2 inline-block text-[11px] font-medium text-accent hover:underline"
        >
          Manifest
        </Link>
      </div>
    </div>
  );
}

export function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 lg:block">
        <Sidebar />
      </aside>

      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-foreground/30"
            onClick={() => setOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-64">
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-5">
            <div className="flex items-center gap-3">
              <button
                className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-panel lg:hidden"
                onClick={() => setOpen((v) => !v)}
                aria-label="Toggle navigation"
              >
                {open ? <X className="size-4" /> : <Menu className="size-4" />}
              </button>
              <div>
                <h1 className="text-base font-semibold tracking-tight sm:text-lg">{title}</h1>
                {subtitle ? (
                  <p className="text-xs text-muted-foreground">{subtitle}</p>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {actions}
              <button
                onClick={toggle}
                aria-label="Toggle theme"
                className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-panel text-muted-foreground hover:text-foreground"
              >
                {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </button>
            </div>
          </div>
        </header>

        <main className="px-4 py-3 sm:px-5">{children}</main>

        <ProvenanceFooter />
      </div>
    </div>
  );
}

export function ProvenanceFooter() {
  const p = posture;
  const items = [
    { k: "Last assessment", v: relativeTime(p.assessed_at), title: absoluteTime(p.assessed_at) },
    { k: "Knowledge base", v: `sha256 ${p.manifest.db_sha256}` },
    {
      k: "Coverage",
      v: `${p.coverage.dimensions_assessed}/${p.coverage.dimensions_total} dimensions · ${p.coverage.percent}%`,
    },
    { k: "Engine", v: `CVM ${p.manifest.cvm_version}` },
    { k: "Scoring model", v: `v${p.scoring_model.version} · ${p.scoring_model.aggregation}` },
    { k: "Missing dimensions", v: p.scoring_model.missing_dimension_policy },
  ];
  return (
    <footer className="mt-3 border-t border-border bg-panel px-4 py-3 sm:px-5">
      <div className="flex flex-wrap gap-x-7 gap-y-2">
        {items.map((i) => (
          <div key={i.k} title={i.title}>
            <div className="section-label">{i.k}</div>
            <div className="num mt-0.5 text-xs text-foreground">{i.v}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Every number on this console is reproducible from the engine version, knowledge base hash
        and scoring model above.
      </p>
    </footer>
  );
}
