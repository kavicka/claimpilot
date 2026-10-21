import type { LineItem, LineItemColumn } from "@crm-ui/react";

import { failedCheckLabel, findingLabel } from "@/lib/enums";
import { humanize } from "@/lib/format";
import type { Field, InvoiceDetail, ValidationCheck } from "@/lib/types";

export interface HeaderGroup {
  key: string;
  title: string;
  fields: { field: Field; label: string }[];
}

const GROUPS: { key: string; title: string; labels: Record<string, string>; arrays?: Record<string, string> }[] = [
  {
    key: "supplier",
    title: "Supplier",
    labels: { supplier_name: "Name", supplier_ico: "IČO", supplier_dic: "DIČ", supplier_vat_id: "VAT ID", supplier_iban: "IBAN" },
  },
  {
    key: "buyer",
    title: "Buyer",
    labels: { buyer_name: "Name", buyer_ico: "IČO", buyer_dic: "DIČ", buyer_vat_id: "VAT ID", customer_number: "Customer number" },
  },
  {
    key: "dates",
    title: "Dates & symbols",
    labels: {
      invoice_number: "Invoice number",
      issue_date: "Issue date",
      tax_point_date: "Tax point date",
      due_date: "Due date",
      variable_symbol: "Variable symbol",
      constant_symbol: "Constant symbol",
      specific_symbol: "Specific symbol",
      order_number: "Order number",
      delivery_note_numbers: "Delivery notes",
      original_invoice_number: "Original invoice",
      proforma_number: "Proforma number",
      proforma_settled: "Settled by proforma",
    },
  },
  {
    key: "totals",
    title: "Totals & VAT recap",
    labels: {
      currency: "Currency",
      total_net: "Net total",
      total_vat: "VAT total",
      total: "Total",
      amount_due: "Amount due",
      second_currency_total: "Total in second currency",
      fx_rate: "FX rate",
      reverse_charge: "Reverse charge",
    },
    arrays: { recap: "VAT recap", fees: "Fee" },
  },
];

const ARRAY = /^([a-z_]+)\[(\d+)\]\.(.+)$/;
const SUB_LABEL: Record<string, string> = { rate: "rate", base: "base", vat: "VAT", label: "label", net: "net" };

/** Header fields in four groups (plus Other for anything unknown), in the order a handler reads them. */
export function groupHeader(fields: Field[]): HeaderGroup[] {
  const out: HeaderGroup[] = GROUPS.map((g) => ({ key: g.key, title: g.title, fields: [] }));
  const other: HeaderGroup = { key: "other", title: "Other", fields: [] };
  const rank = new Map<number, number>();
  for (const f of fields) {
    const m = ARRAY.exec(f.field);
    let placed = false;
    GROUPS.forEach((g, gi) => {
      if (placed) return;
      if (g.labels[f.field]) {
        out[gi]!.fields.push({ field: f, label: g.labels[f.field]! });
        rank.set(f.id, Object.keys(g.labels).indexOf(f.field));
        placed = true;
      } else if (m && g.arrays?.[m[1]!]) {
        const i = Number(m[2]);
        out[gi]!.fields.push({ field: f, label: `${g.arrays[m[1]!]} ${i + 1} ${SUB_LABEL[m[3]!] ?? humanize(m[3]!)}` });
        const arrays = Object.keys(g.arrays);
        rank.set(f.id, 100 + arrays.indexOf(m[1]!) * 1000 + i * 10 + Object.keys(SUB_LABEL).indexOf(m[3]!));
        placed = true;
      }
    });
    if (!placed) other.fields.push({ field: f, label: f.field === "page_note" ? "Page note" : humanize(f.field.replace(/[[\].]+/g, "_")) });
  }
  for (const g of out) g.fields.sort((a, b) => (rank.get(a.field.id) ?? 0) - (rank.get(b.field.id) ?? 0));
  return [...out, other].filter((g) => g.fields.length > 0);
}

const LINE_COLUMNS: LineItemColumn[] = [
  { key: "supplier_code", header: "Code", width: 84 },
  { key: "ean", header: "EAN", width: 116 },
  { key: "name", header: "Item", width: 180 },
  { key: "quantity", header: "Qty", kind: "number", width: 60 },
  { key: "unit", header: "Unit", width: 56 },
  { key: "unit_price", header: "Unit price", kind: "number", width: 88 },
  { key: "discount_pct", header: "Disc. %", kind: "number", width: 68 },
  { key: "struct_discount_pct", header: "Struct. disc. %", kind: "number", width: 104 },
  { key: "promo_discount_pct", header: "Promo %", kind: "number", width: 72 },
  { key: "net_unit_price", header: "Net unit", kind: "number", width: 84 },
  { key: "gross_unit_price", header: "Gross unit", kind: "number", width: 88 },
  { key: "line_net", header: "Net", kind: "number", width: 88 },
  { key: "vat_rate", header: "VAT %", kind: "number", width: 64 },
  { key: "vat_amount", header: "VAT", kind: "number", width: 76 },
  { key: "line_gross", header: "Gross", kind: "number", width: 88 },
  { key: "sukl_code", header: "ŠÚKL", width: 76 },
  { key: "origin", header: "Origin", width: 68 },
  { key: "customs_code", header: "Customs code", width: 104 },
];

const BATCH = /^batches\[(\d+)\]\.(batch|expiry|quantity)$/;
const BATCH_HEADER: Record<string, string> = { batch: "Batch", expiry: "Expiry", quantity: "Batch qty" };
const BATCH_ORDER = ["batch", "expiry", "quantity"];

/** Columns for the fields that occur on at least one line, in the order they are printed. */
export function lineColumns(invoice: InvoiceDetail): LineItemColumn[] {
  const present = new Set(invoice.lines.flatMap((l) => Object.keys(l.fields)));
  const known = LINE_COLUMNS.filter((c) => present.has(c.key));
  const batches = [...present]
    .map((k) => ({ k, m: BATCH.exec(k) }))
    .filter((x) => x.m)
    .sort((a, b) => Number(a.m![1]) - Number(b.m![1]) || BATCH_ORDER.indexOf(a.m![2]!) - BATCH_ORDER.indexOf(b.m![2]!))
    .map(({ k, m }) => {
      const i = Number(m![1]);
      return {
        key: k,
        header: `${BATCH_HEADER[m![2]!]}${i > 0 ? ` ${i + 1}` : ""}`,
        kind: m![2] === "quantity" ? ("number" as const) : ("text" as const),
        width: m![2] === "quantity" ? 76 : 88,
      };
    });
  const used = new Set([...known.map((c) => c.key), ...batches.map((c) => c.key)]);
  const rest = [...present].filter((k) => !used.has(k)).sort().map((k) => ({ key: k, header: humanize(k.replace(/[[\].]+/g, "_")) }));
  return [...known, ...batches, ...rest];
}

function checkText(name: string, detail: string | null | undefined): string {
  const label = failedCheckLabel(name);
  return detail ? `${label} (${detail})` : label;
}

/** Failed checks on one field: from the field's own checks and from validation entries naming it. */
export function fieldProblems(field: Field, path: string, validation: ValidationCheck[]): string[] {
  const failed = validation.filter((c) => !c.ok && c.fields.includes(path));
  const names = new Set<string>();
  const out: string[] = [];
  for (const c of failed) {
    if (names.has(c.name)) continue;
    names.add(c.name);
    out.push(checkText(c.name, c.detail));
  }
  for (const [name, ok] of Object.entries(field.checks ?? {})) {
    if (ok === false && !names.has(name)) {
      names.add(name);
      out.push(checkText(name, null));
    }
  }
  return out;
}

/** The matching findings for each line, by 0-based position in the lines array. */
export function lineFindings(invoice: InvoiceDetail): Map<number, string[]> {
  const out = new Map<number, string[]>();
  for (const f of invoice.matching?.findings ?? []) {
    if (f.line === null || f.line === undefined) continue;
    const text = f.detail ? `${findingLabel(f.kind)}: ${f.detail}` : findingLabel(f.kind);
    out.set(f.line, [...(out.get(f.line) ?? []), text]);
  }
  return out;
}

export function lineItems(invoice: InvoiceDetail, columns: LineItemColumn[]): LineItem[] {
  const findings = lineFindings(invoice);
  return invoice.lines.map((line, index) => ({
    key: String(line.n),
    label: String(line.n),
    flags: findings.get(index) ?? [],
    cells: Object.fromEntries(
      columns
        .filter((c) => line.fields[c.key])
        .map((c) => {
          const f = line.fields[c.key]!;
          return [
            c.key,
            {
              id: String(f.id),
              value: f.value,
              corrected: f.corrected,
              flags: fieldProblems(f, `lines[${line.n}].${c.key}`, invoice.validation),
            },
          ];
        }),
    ),
  }));
}

/** Resolves a validation path ("total", "lines[2].quantity") to the field it names. */
export function fieldByPath(invoice: InvoiceDetail, path: string): Field | null {
  const m = /^lines\[(\d+)\]\.(.+)$/.exec(path);
  if (!m) return invoice.header.find((f) => f.field === path) ?? null;
  return invoice.lines.find((l) => l.n === Number(m[1]))?.fields[m[2]!] ?? null;
}

/** "Line 2 · Qty" for a line field, the header label otherwise. */
export function pathLabel(path: string, columns: LineItemColumn[]): string {
  const m = /^lines\[(\d+)\]\.(.+)$/.exec(path);
  if (!m) {
    for (const g of groupHeader([{ id: 0, field: path } as Field])) {
      const label = g.fields[0]?.label;
      if (label) return g.key === "supplier" || g.key === "buyer" ? `${g.title} ${label === "Name" ? "name" : label}` : label;
    }
    return humanize(path);
  }
  const header = columns.find((c) => c.key === m[2])?.header ?? humanize(m[2]!.replace(/[[\].]+/g, "_"));
  return `Line ${m[1]} · ${header}`;
}
