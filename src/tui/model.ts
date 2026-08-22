import type { AgentScan } from "../agents/discover.js";

export interface AgentRow {
  name: string;
  status: string;
  skills: string;
  config: string;
  creds: string;
  method: string;
}

export function agentRows(scans: readonly AgentScan[]): AgentRow[] {
  return scans.map((scan) => ({
    name: scan.name,
    status: scan.found ? "found" : "not found",
    skills: String(scan.skills.length),
    config: scan.configPath ?? "—",
    creds: scan.hasCredentials ? "yes" : "no",
    method: scan.install?.method ?? "—",
  }));
}

export const AGENT_HEADERS = ["name", "status", "skills", "creds", "method", "config"] as const;

export function renderTable(
  headers: readonly string[],
  rows: readonly (readonly string[])[],
): string[] {
  const widths = headers.map((header, column) => {
    const cellLengths = rows.map((row) => row[column]?.length ?? 0);
    return Math.max(header.length, ...cellLengths);
  });
  const format = (cells: readonly string[]): string =>
    cells.map((cell, column) => (cell ?? "").padEnd(widths[column] ?? 0)).join("  ");
  const divider = headers.map((_header, column) => "-".repeat(widths[column] ?? 0)).join("  ");
  return [format(headers), divider, ...rows.map(format)];
}

export function agentTableLines(scans: readonly AgentScan[]): string[] {
  const rows = agentRows(scans).map((row) => [row.name, row.status, row.skills, row.creds, row.method, row.config]);
  return renderTable([...AGENT_HEADERS], rows);
}
