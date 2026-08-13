import {
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

export const TECH_ICONS: Record<
  string,
  { icon: LucideIcon; color: string; colorDark: string; label: string }
> = {
  apache: { icon: Feather, color: "#D22128", colorDark: "#F87171", label: "Apache HTTPD" },
  nginx: { icon: Server, color: "#009639", colorDark: "#4ADE80", label: "nginx" },
  docker: { icon: Container, color: "#2496ED", colorDark: "#60A5FA", label: "Docker" },
  dockerfile: { icon: FileCode, color: "#2496ED", colorDark: "#60A5FA", label: "Dockerfile" },
  kubernetes: { icon: Boxes, color: "#326CE5", colorDark: "#818CF8", label: "Kubernetes" },
  mysql: { icon: Database, color: "#00758F", colorDark: "#22D3EE", label: "MySQL" },
  postgres: { icon: Database, color: "#336791", colorDark: "#7DD3FC", label: "PostgreSQL" },
  redis: { icon: Database, color: "#DC382D", colorDark: "#FB7185", label: "Redis" },
  ssh: { icon: Terminal, color: "#4B5563", colorDark: "#9AA5B4", label: "SSH" },
  ubuntu: { icon: Server, color: "#E95420", colorDark: "#FB923C", label: "Ubuntu" },
  tomcat: { icon: Box, color: "#BF9600", colorDark: "#FCD34D", label: "Apache Tomcat" },
  azure: { icon: Cloud, color: "#0078D4", colorDark: "#38BDF8", label: "Azure IaC" },
};

export const fmtScore = (v: number | null) => (v === null ? "—" : v.toFixed(1));

export const relativeTime = (iso: string, now = new Date("2026-08-12T14:40:00Z")) => {
  const diff = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
};

export const absoluteTime = (iso: string) =>
  new Date(iso).toUTCString().replace("GMT", "UTC");

export const techIcon = (key: string) =>
  TECH_ICONS[key] ?? { icon: Server, color: "#4B5563", colorDark: "#9AA5B4", label: key };
