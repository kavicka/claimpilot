import { humanize } from "@/lib/format";
import type { Field } from "@/lib/types";

export interface FieldGroup {
  key: string;
  /** null for the document's top-level fields */
  title: string | null;
  fields: { field: Field; label: string }[];
}

const ARRAY_PATH = /^([A-Za-z0-9_]+)\[(\d+)\](?:\.(.+))?$/;

function singular(name: string): string {
  const h = humanize(name);
  if (h.endsWith("ies")) return `${h.slice(0, -3)}y`;
  if (h.endsWith("s") && !h.endsWith("ss")) return h.slice(0, -1);
  return h;
}

export function fieldLabel(path: string): string {
  const m = ARRAY_PATH.exec(path);
  if (!m) return humanize(path);
  return m[3] ? humanize(m[3].replace(/\./g, "_")) : `${singular(m[1]!)} ${Number(m[2]) + 1}`;
}

/** Top-level fields first, then one group per array element (line_items[2] -> "Line item 3"). */
export function groupFields(fields: Field[]): FieldGroup[] {
  const top: FieldGroup = { key: "", title: null, fields: [] };
  const arrays = new Map<string, FieldGroup & { rank: number; index: number }>();
  const nameRank = new Map<string, number>();
  for (const f of fields) {
    const m = ARRAY_PATH.exec(f.field);
    if (!m || !m[3]) {
      top.fields.push({ field: f, label: fieldLabel(f.field) });
      continue;
    }
    const name = m[1]!;
    const index = Number(m[2]);
    if (!nameRank.has(name)) nameRank.set(name, nameRank.size);
    const key = `${name}[${index}]`;
    let g = arrays.get(key);
    if (!g) {
      g = { key, title: `${singular(name)} ${index + 1}`, fields: [], rank: nameRank.get(name)!, index };
      arrays.set(key, g);
    }
    g.fields.push({ field: f, label: humanize(m[3].replace(/\./g, "_")) });
  }
  const sortedArrays = [...arrays.values()].sort((a, b) => a.rank - b.rank || a.index - b.index);
  return top.fields.length ? [top, ...sortedArrays] : sortedArrays;
}

export function failedChecks(f: Field): string[] {
  return Object.entries(f.checks ?? {})
    .filter(([, ok]) => ok === false)
    .map(([name]) => name);
}

export type Level = "high" | "medium" | "low" | "empty" | "unknown";

export function confidenceLevel(f: Field): Level {
  if (f.value === null || f.value === "") return "empty";
  if (f.confidence === null) return "unknown";
  if (f.confidence >= 0.9) return "high";
  if (f.confidence >= 0.7) return "medium";
  return "low";
}

/** Fields a handler should look at: missing, ungrounded, low confidence or a failed check. */
export function isFlagged(f: Field): boolean {
  const level = confidenceLevel(f);
  return level === "empty" || level === "low" || !f.grounded || failedChecks(f).length > 0;
}
