"use client";

import { Alert, EmptyState, InlineLink, Spinner, Tabs, useToast, type TabItem } from "@claimpilot/ui";
import { useMemo, useState } from "react";

import { isFlagged } from "@/components/claim/field-utils";
import { HiddenTextWarning } from "@/components/claim/injection-warning";
import { PipelinePanel } from "@/components/claim/pipeline-panel";
import { api } from "@/lib/api";
import { INVOICE_PIPELINE_STATUSES } from "@/lib/enums";
import type { Field, FieldPatchResult, InvoiceDetail } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

import { ChecksPanel } from "./checks-panel";
import { HeaderPanel } from "./header-panel";
import { InvoiceHeader } from "./invoice-header";
import { InvoicePages, type PageBox, type PageMark } from "./invoice-pages";
import { lineColumns, lineItems } from "./invoice-utils";
import { LinesPanel } from "./lines-panel";

type PanelKey = "header" | "lines" | "checks" | "pipeline";

type Selection = { kind: "field"; id: number; nonce: number } | { kind: "line"; n: number; nonce: number };

/** The worker owns the invoice: still in the pipeline, or approved and being exported. */
function owned(invoice: InvoiceDetail | undefined): boolean {
  return !invoice || INVOICE_PIPELINE_STATUSES.includes(invoice.status) || invoice.status === "APPROVED";
}

export function InvoiceView({ id }: { id: string }) {
  const notify = useToast();
  const { data: invoice, error, loading, reload, mutate } = useFetch<InvoiceDetail>(`invoice:${id}`, () => api.invoice(id), {
    pollMs: 10000,
    pollWhile: owned,
  });
  const [panel, setPanel] = useState<PanelKey>("lines");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [hoverLine, setHoverLine] = useState<number | null>(null);

  const columns = useMemo(() => (invoice ? lineColumns(invoice) : []), [invoice]);

  // Every field with the line it belongs to (null for header fields).
  const fields = useMemo(() => {
    const map = new Map<number, { field: Field; line: number | null; name: string }>();
    if (!invoice) return map;
    for (const f of invoice.header) map.set(f.id, { field: f, line: null, name: f.field });
    for (const l of invoice.lines) for (const [name, f] of Object.entries(l.fields)) map.set(f.id, { field: f, line: l.n, name });
    return map;
  }, [invoice]);

  if (loading) {
    return (
      <div className="cp-text-cell flex h-full items-center justify-center gap-8 text-ink-subtle" role="status">
        <Spinner /> Loading invoice
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="mx-auto max-w-[560px] px-32 py-64">
        {error === "no such invoice" ? (
          <EmptyState
            icon="file-unknown"
            title="Invoice not found."
            description={`No invoice has the ID ${id}.`}
            action={<InlineLink href="/invoices">Back to the invoices</InlineLink>}
          />
        ) : (
          <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
            {error ?? "The invoice could not be loaded."}
          </Alert>
        )}
      </div>
    );
  }

  const running = owned(invoice);
  const editable = invoice.status === "IN_REVIEW";

  function selectField(field: Field) {
    setSelection((s) => ({ kind: "field", id: field.id, nonce: (s?.nonce ?? 0) + 1 }));
  }
  function selectLine(n: number) {
    setSelection((s) => ({ kind: "line", n, nonce: (s?.nonce ?? 0) + 1 }));
  }

  const selected = selection?.kind === "field" ? (fields.get(selection.id) ?? null) : null;
  const selectedLine = selection?.kind === "line" ? selection.n : (selected?.line ?? null);
  const rowOf = (n: number | null) => (n === null ? null : (invoice.lines.find((l) => l.n === n)?.row ?? null));

  const marks: PageMark[] = [];
  let target: { page: number; bbox: PageMark["bbox"] | null; nonce: number } | null = null;
  let notice: string | null = null;
  if (selected && selection) {
    const f = selected.field;
    const row = rowOf(selected.line);
    if (row) marks.push({ key: `row-${selected.line}`, page: row.page, bbox: row.bbox, tone: "hover" });
    const label = selected.line === null ? f.field : `lines[${selected.line}].${selected.name}`;
    if (f.page !== null && f.bbox) {
      marks.push({ key: `field-${f.id}`, page: f.page, bbox: f.bbox, tone: "select", label });
      target = { page: f.page, bbox: f.bbox, nonce: selection.nonce };
    } else if (row) {
      target = { page: row.page, bbox: row.bbox, nonce: selection.nonce };
      notice = `No box for this value. Showing line ${selected.line}.`;
    } else if (f.page !== null) {
      target = { page: f.page, bbox: null, nonce: selection.nonce };
      notice = `No box for this field. Showing page ${f.page}.`;
    } else {
      notice = "This field has no position in the document.";
    }
  } else if (selection?.kind === "line") {
    const row = rowOf(selection.n);
    if (row) {
      marks.push({ key: `row-${selection.n}`, page: row.page, bbox: row.bbox, tone: "select", label: `Line ${selection.n}` });
      target = { page: row.page, bbox: row.bbox, nonce: selection.nonce };
    } else {
      notice = `No box for line ${selection.n}.`;
    }
  }
  const hovered = hoverLine !== null && hoverLine !== selectedLine ? rowOf(hoverLine) : null;
  if (hovered) marks.push({ key: `hover-${hoverLine}`, page: hovered.page, bbox: hovered.bbox, tone: "hover" });

  const boxes: PageBox[] = [
    ...invoice.header
      .filter((f) => f.page !== null && f.bbox)
      .map((f) => ({
        key: `f-${f.id}`,
        page: f.page!,
        bbox: f.bbox!,
        label: f.field,
        onSelect: () => {
          selectField(f);
          setPanel("header");
        },
      })),
    ...invoice.lines
      .filter((l) => l.row)
      .map((l) => ({
        key: `l-${l.n}`,
        page: l.row!.page,
        bbox: l.row!.bbox,
        label: `Line ${l.n}`,
        onSelect: () => {
          selectLine(l.n);
          setPanel("lines");
        },
      })),
  ];

  function onFieldSaved(result: FieldPatchResult) {
    const patch = (f: Field) =>
      f.id === result.id ? { ...f, value: result.value, value_norm: result.value_norm, corrected: true, grounded: true, confidence: 1 } : f;
    mutate((inv) => ({
      ...inv,
      version: result.claim_version,
      needs_revalidation: true, // checks, matching and routing were computed from the old value
      header: inv.header.map(patch),
      lines: inv.lines.map((l) => ({ ...l, fields: Object.fromEntries(Object.entries(l.fields).map(([k, f]) => [k, patch(f)])) })),
    }));
    notify("success", "Field corrected", "Saved and logged. Reassess before approving.");
  }

  const supplier = invoice.header.find((f) => f.field === "supplier_name")?.value ?? null;
  const headerFlagged = invoice.header.filter(isFlagged).length;
  const items = lineItems(invoice, columns);
  const linesFlagged = items.filter((r) => (r.flags?.length ?? 0) > 0 || Object.values(r.cells).some((c) => c?.flags?.length)).length;
  const failedChecks = invoice.validation.filter((c) => !c.ok).length + (invoice.matching?.findings.length ?? 0);
  const stepErrors = invoice.steps.some((s) => s.status !== "ok");
  const hidden = (invoice.document?.hidden_text ?? []).map((h) => ({ ...h, filename: invoice.document!.filename }));
  const injection = invoice.routing.filter((h) => h.rule === "I3").map((h) => h.detail);

  const tabs: TabItem<PanelKey>[] = [
    {
      key: "header",
      label: "Header",
      count: invoice.header.length,
      flag: headerFlagged ? "warning" : undefined,
      title: headerFlagged ? `${headerFlagged} fields to check` : undefined,
    },
    {
      key: "lines",
      label: "Lines",
      count: invoice.lines.length,
      flag: linesFlagged ? "danger" : undefined,
      title: linesFlagged ? `${linesFlagged} lines with problems` : undefined,
    },
    {
      key: "checks",
      label: "Checks",
      count: failedChecks || undefined,
      flag: failedChecks ? "danger" : undefined,
      title: failedChecks ? `${failedChecks} failed checks and findings` : undefined,
    },
    { key: "pipeline", label: "Pipeline", flag: stepErrors ? "danger" : undefined, title: stepErrors ? "Some steps failed or were retried" : undefined },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <InvoiceHeader invoice={invoice} supplier={supplier} error={error} running={running} onChanged={reload} />
      <HiddenTextWarning
        title="This invoice talks to the AI system or hides text from the reader"
        body="Hidden text was kept away from the models, and the invoice went to a senior handler. Check the document yourself: extracted values may have been steered."
        hits={injection}
        hidden={hidden}
      />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,0.9fr)_minmax(560px,1.1fr)]">
        <InvoicePages document={invoice.document} marks={marks} boxes={boxes} target={target} notice={notice} />
        <section className="flex min-h-0 flex-col bg-surface hairline-l">
          <Tabs variant="line" tabs={tabs} value={panel} onValueChange={setPanel} label="Invoice details" className="px-20 pt-12" />
          <div className="pane-scroll min-h-0 flex-1 overflow-y-auto" role="tabpanel" aria-label={tabs.find((t) => t.key === panel)?.label as string}>
            {panel === "header" ? (
              <HeaderPanel
                invoice={invoice}
                selectedFieldId={selection?.kind === "field" ? selection.id : null}
                editable={editable}
                onSelect={selectField}
                onSaved={onFieldSaved}
              />
            ) : panel === "lines" ? (
              <LinesPanel
                invoice={invoice}
                columns={columns}
                selectedFieldId={selection?.kind === "field" ? selection.id : null}
                selectedLine={selectedLine}
                editable={editable}
                onSelectField={selectField}
                onSelectLine={selectLine}
                onHoverLine={setHoverLine}
                onSaved={onFieldSaved}
              />
            ) : panel === "checks" ? (
              <ChecksPanel
                invoice={invoice}
                columns={columns}
                onSelectField={(f) => {
                  selectField(f);
                  setPanel(fields.get(f.id)?.line === null ? "header" : "lines");
                }}
                onSelectLine={(n) => {
                  selectLine(n);
                  setPanel("lines");
                }}
              />
            ) : (
              <PipelinePanel
                steps={invoice.steps.map((s) => ({ ...s, attempt: s.attempt ?? 1, tokens: s.tokens ?? 0 }))}
                audit={invoice.audit}
                traceUrl={null}
              />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
