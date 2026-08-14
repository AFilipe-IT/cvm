import {
  AppWindow,
  Box,
  Boxes,
  Cloud,
  Container,
  Database,
  EyeOff,
  Feather,
  FileCode,
  Globe,
  KeyRound,
  Package,
  Router,
  Server,
  Shield,
  SlidersHorizontal,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import type { DimensionId, Severity } from "./types";

export const severityVar = (s: Severity | null): string => {
  switch (s) {
    case "Low":
      return "var(--sev-low)";
    case "Medium":
      return "var(--sev-medium)";
    case "High":
      return "var(--sev-high)";
    case "Critical":
      return "var(--sev-critical)";
    default:
      return "var(--sev-none)";
  }
};

export const severityForScore = (score: number): Severity => {
  if (score === 0) return "None";
  if (score < 4) return "Low";
  if (score < 7) return "Medium";
  if (score < 9) return "High";
  return "Critical";
};

export const SEVERITY_BANDS: { severity: Severity; range: string }[] = [
  { severity: "None", range: "0.0" },
  { severity: "Low", range: "0.1–3.9" },
  { severity: "Medium", range: "4.0–6.9" },
  { severity: "High", range: "7.0–8.9" },
  { severity: "Critical", range: "9.0–10.0" },
];

export const KPI_ACCENTS = {
  blue: "var(--kpi-blue)",
  teal: "var(--kpi-teal)",
  orange: "var(--kpi-orange)",
  purple: "var(--kpi-purple)",
  red: "var(--kpi-red)",
  amber: "var(--kpi-amber)",
} as const;
export type KpiAccent = keyof typeof KPI_ACCENTS;

export const DIMENSION_META: Record<
  DimensionId,
  { icon: LucideIcon; accent: string; short: string }
> = {
  configuration: { icon: SlidersHorizontal, accent: KPI_ACCENTS.blue, short: "Config" },
  permissions: { icon: KeyRound, accent: KPI_ACCENTS.purple, short: "Permissions" },
  exposure: { icon: Globe, accent: KPI_ACCENTS.teal, short: "Exposure" },
  secrets: { icon: EyeOff, accent: KPI_ACCENTS.orange, short: "Secrets" },
  patch: { icon: Package, accent: KPI_ACCENTS.amber, short: "Patch" },
  hardening: { icon: Shield, accent: KPI_ACCENTS.blue, short: "Hardening" },
};

type TechIconMeta = {
  icon: LucideIcon;
  color: string;
  colorDark: string;
  label: string;
};

/* Brand colours, not severity colours. The score beside the icon is what says
   whether a target is healthy — which is why Redis stays red at score 0.
   The dark values are lightened: the brand blues and greens fall under the
   minimum contrast against the dark panel. */
export const TECH_ICONS: Record<string, TechIconMeta> = {
  // Keys are the names the API actually returns — the plugin registry's
  // `apache-httpd` and `postgresql`, not the shortened `apache`/`postgres`
  // that never matched anything. The short forms stay as aliases because the
  // fetch catalog uses `apache` for the same technology.
  "apache-httpd": { icon: Feather, color: "#D22128", colorDark: "#F87171", label: "Apache HTTPD" },
  apache: { icon: Feather, color: "#D22128", colorDark: "#F87171", label: "Apache HTTPD" },
  nginx: { icon: Globe, color: "#009639", colorDark: "#4ADE80", label: "nginx" },
  docker: { icon: Container, color: "#2496ED", colorDark: "#60A5FA", label: "Docker" },
  dockerfile: { icon: FileCode, color: "#2496ED", colorDark: "#60A5FA", label: "Dockerfile" },
  kubernetes: { icon: Boxes, color: "#326CE5", colorDark: "#818CF8", label: "Kubernetes" },
  mysql: { icon: Database, color: "#00758F", colorDark: "#22D3EE", label: "MySQL" },
  postgresql: { icon: Database, color: "#336791", colorDark: "#7DD3FC", label: "PostgreSQL" },
  postgres: { icon: Database, color: "#336791", colorDark: "#7DD3FC", label: "PostgreSQL" },
  redis: { icon: Database, color: "#DC382D", colorDark: "#FB7185", label: "Redis" },
  ssh: { icon: Terminal, color: "#4B5563", colorDark: "#9AA5B4", label: "SSH" },
  ubuntu: { icon: Server, color: "#E95420", colorDark: "#FB923C", label: "Ubuntu" },
  tomcat: { icon: Box, color: "#BF9600", colorDark: "#FCD34D", label: "Apache Tomcat" },
  "azure-iac": { icon: Cloud, color: "#0078D4", colorDark: "#38BDF8", label: "Azure IaC" },
  azure: { icon: Cloud, color: "#0078D4", colorDark: "#38BDF8", label: "Azure IaC" },
};

/* The fetch catalog carries 43 services that are not installed — `rhel9`,
   `windows-server-2022`, `cisco-ios`, `oracle-linux-8`. Matched by exact name
   alone, 39 of the 49 names the console can show fell into the same grey
   square, which is most of the plugins page.

   So the FAMILY decides when the name does not: an OS is a server, a database
   is a cylinder, a network appliance is a router. Order matters —
   `oracle-linux-8` has to hit the linux rule before the oracle-db one, or it
   would dress up as a database. */
const TECH_FAMILIES: [RegExp, TechIconMeta][] = [
  [/^apache($|-)/, { icon: Feather, color: "#D22128", colorDark: "#F87171", label: "Apache" }],
  [/ubuntu|debian/, { icon: Server, color: "#E95420", colorDark: "#FB923C", label: "Ubuntu" }],
  [
    /rhel|oracle-linux|sles|centos|fedora/,
    { icon: Server, color: "#EE0000", colorDark: "#F87171", label: "Red Hat family" },
  ],
  [
    /windows|^iis/,
    { icon: AppWindow, color: "#0078D4", colorDark: "#38BDF8", label: "Windows" },
  ],
  [/macos/, { icon: Server, color: "#52525B", colorDark: "#A1A1AA", label: "macOS" }],
  [/aix|solaris/, { icon: Server, color: "#6D28D9", colorDark: "#C4B5FD", label: "UNIX" }],
  [
    /mongo|mariadb|sqlserver|oracle-db|db2|epas|postgres/,
    { icon: Database, color: "#0F766E", colorDark: "#5EEAD4", label: "Database" },
  ],
  [
    /cisco|juniper|arista|palo-alto|f5-|ndm|fw$/,
    { icon: Router, color: "#B45309", colorDark: "#FBBF24", label: "Network device" },
  ],
  [
    /openshift|rke2|kube/,
    { icon: Boxes, color: "#326CE5", colorDark: "#818CF8", label: "Kubernetes" },
  ],
  [/jboss/, { icon: Box, color: "#BF9600", colorDark: "#FCD34D", label: "JBoss" }],
];

export const fmtScore = (v: number | null) => (v === null ? "—" : v.toFixed(1));

// `now` defaulted to a frozen date while the console ran on fixtures, so the
// mock's timestamps always read as recent. Against live data that would report
// every age relative to a date in the past — wrong, and increasingly so.
export const relativeTime = (iso: string, now = new Date()) => {
  const diff = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
};

export const absoluteTime = (iso: string) =>
  new Date(iso).toUTCString().replace("GMT", "UTC");

// Exact name first, family second, generic last: a brand-new target still
// renders without breaking the list, and one from a known family arrives
// already dressed without needing a line of its own.
export const techIcon = (key: string): TechIconMeta => {
  const k = key.toLowerCase();
  const exact = TECH_ICONS[k];
  if (exact) return exact;
  const family = TECH_FAMILIES.find(([re]) => re.test(k));
  // The family label names the family, not this target — keep the target's
  // own name so the tooltip does not claim `rhel9` is called "Red Hat family".
  if (family) return { ...family[1], label: key };
  return { icon: Server, color: "#4B5563", colorDark: "#9AA5B4", label: key };
};
