import type { Cell } from "./db";

const decimals = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const grouped = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Years and ids read better without thousands separators. */
const plainColumn = (column: string) => /year|(^|_)id$|Id$/i.test(column);

export function formatCell(v: Cell, column = ""): string {
  if (v === null) return "NULL";
  if (typeof v === "number") {
    if (Number.isInteger(v))
      return plainColumn(column) ? String(v) : grouped.format(v);
    return decimals.format(v);
  }
  return String(v);
}

export const formatCompact = (v: number) =>
  Math.abs(v) >= 10_000 ? compact.format(v) : decimals.format(v);

export const formatMB = (bytes: number) => `${Math.round(bytes / 2 ** 20)} MB`;

export function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatEta(s: number): string {
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  return `${Math.round(s / 60)} min`;
}

export const pct = (x: number) => `${Math.round(x * 100)}%`;
