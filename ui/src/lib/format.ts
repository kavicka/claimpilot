const eurFormat = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const intFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

export function eur(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "–";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? eurFormat.format(n) : String(value);
}

export function money(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined || value === "") return "–";
  const n = Number(value);
  if (!Number.isFinite(n)) return `${value} ${currency}`;
  try {
    return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export function int(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : intFormat.format(value);
}

export function age(hours: number): string {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  const d = Math.floor(hours / 24);
  const h = Math.round(hours - d * 24);
  return h ? `${d} d ${h} h` : `${d} d`;
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

export function seconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "–";
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  // Eval reports use a compact stamp: 20261009T182522Z
  const compact = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(iso);
  const d = compact
    ? new Date(Date.UTC(+compact[1]!, +compact[2]! - 1, +compact[3]!, +compact[4]!, +compact[5]!, +compact[6]!))
    : new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTime.format(d);
}

/** "93.2 % (423/454)" for ratios, a plain number for counts (den = 0). */
export function metric(m: { value: number; num: number; den: number }): string {
  if (m.den > 0) return `${(m.value * 100).toFixed(1)} % (${m.num}/${m.den})`;
  return Number.isInteger(m.value) ? intFormat.format(m.value) : m.value.toFixed(2);
}

export function percent(ratio: number | null | undefined): string {
  return ratio === null || ratio === undefined ? "–" : `${(ratio * 100).toFixed(1)} %`;
}

const ACRONYMS: Record<string, string> = {
  icd10: "ICD-10",
  iban: "IBAN",
  id: "ID",
  eur: "EUR",
  fx: "FX",
  llm: "LLM",
  pii: "PII",
  ocr: "OCR",
};

/** snake_case -> "Sentence case", keeping known acronyms. */
export function humanize(name: string): string {
  const words = name.split(/[_\s]+/).filter(Boolean);
  return words
    .map((w, i) => {
      const lower = w.toLowerCase();
      if (ACRONYMS[lower]) return ACRONYMS[lower];
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    })
    .join(" ");
}

export function firstLine(text: string, max = 140): string {
  const line = text.split("\n", 1)[0] ?? "";
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
}
