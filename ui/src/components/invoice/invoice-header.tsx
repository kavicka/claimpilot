"use client";

import { Alert, AppHeader, Crumbs, Tag, Tooltip } from "@claimpilot/ui";
import { useState } from "react";

import { CaseActionDialog } from "@/components/claim/action-dialog";
import { ActionButton, Meta } from "@/components/claim/claim-header";
import { useUser } from "@/components/shell/auth";
import { api } from "@/lib/api";
import { INVOICE_KIND, categoryEntry, queueEntry, statusEntry } from "@/lib/enums";
import { firstLine, money } from "@/lib/format";
import type { ClaimAction, InvoiceDetail } from "@/lib/types";

function consequence(action: ClaimAction, invoice: InvoiceDetail): string {
  switch (action) {
    case "approve":
      return invoice.total
        ? `The invoice goes to the ERP as Peppol UBL with a total of ${money(invoice.total, invoice.currency ?? "EUR")}.`
        : "The invoice goes to the ERP as Peppol UBL. No total was read.";
    case "request-info":
      return "The invoice moves to Needs info and waits for the supplier.";
    case "escalate":
      return "The invoice moves to the senior queue. Only a senior handler can decide on it there.";
    case "reject":
      return "The invoice is closed and not paid.";
    case "retry":
      return "The invoice starts over from reading its document. Use it after the cause of the failure is fixed.";
    case "reassess":
      return "Validation, ERP matching and routing run again on the corrected fields. Extraction does not run again, so your corrections stay.";
  }
}

export function InvoiceHeader({
  invoice,
  supplier,
  error,
  running,
  onChanged,
}: {
  invoice: InvoiceDetail;
  supplier: string | null;
  error?: string;
  running: boolean;
  onChanged: () => void;
}) {
  const user = useUser();
  const [action, setAction] = useState<ClaimAction | null>(null);
  const status = statusEntry(invoice.status);
  const queue = queueEntry(invoice.queue);
  const kind = categoryEntry(INVOICE_KIND, invoice.kind);
  const inReview = invoice.status === "IN_REVIEW";
  const notInReview = `Available while the invoice is in review. Status now: ${status.label}.`;
  const seniorQueue = invoice.queue === "senior" || invoice.queue === "fraud_review";
  const seniorOnly = seniorQueue && user.role !== "senior";
  const stale = inReview && invoice.needs_revalidation;
  const decide = !inReview ? notInReview : seniorOnly ? "Invoices in this queue need a senior handler." : null;
  const back = invoice.queue && inReview ? `/invoices?tab=${invoice.queue}` : "/invoices";
  const exportErrors = invoice.export?.errors ?? [];
  const refused = exportErrors.length > 0 && invoice.status !== "EXPORTED";
  const exporting = invoice.status === "APPROVED";

  return (
    <header className="shrink-0">
      <AppHeader
        crumbs={
          <Crumbs
            items={[
              { label: "Invoices", href: "/invoices" },
              { label: queue?.label ?? "Queue", href: back },
              { label: invoice.reference },
            ]}
            onCopy={() => navigator.clipboard?.writeText(invoice.reference)}
          />
        }
        meta={running ? "Refreshes every 10 seconds" : undefined}
      />

      <div className="flex items-start gap-24 px-24 pb-16 pt-20 hairline-b">
        <div className="flex min-w-0 flex-1 flex-col gap-14">
          <div className="flex flex-wrap items-center gap-10">
            <h1 className="cp-text-title-xl text-ink">{invoice.reference}</h1>
            <Tag tone={status.tone} icon={status.icon ?? null} size="md">
              {status.label}
            </Tag>
            {queue ? (
              <Tag tone={queue.tone} dot size="md">
                {queue.label}
              </Tag>
            ) : (
              <Tag tone="neutral" size="md">
                Not routed
              </Tag>
            )}
          </div>
          <dl className="grid max-w-[820px] grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))] gap-16">
            <Meta label="Supplier">{supplier ?? <span className="text-ink-subtle">Not read</span>}</Meta>
            <Meta label="Kind">{kind ? kind.label : "–"}</Meta>
            <Meta label="Invoice number">{invoice.invoice_number ?? "–"}</Meta>
            <Meta label="Order">{invoice.matching?.order ?? "–"}</Meta>
            <Meta label="ERP">
              {invoice.erp_id ? (
                <span className="flex items-center gap-8">
                  {invoice.erp_id}
                  <a
                    href={`/api/review/invoices/${encodeURIComponent(invoice.id)}/ubl`}
                    download
                    className="cp-text-label text-link underline underline-offset-2"
                  >
                    Download UBL
                  </a>
                </span>
              ) : (
                "–"
              )}
            </Meta>
          </dl>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-12">
          <div className="flex flex-col items-end gap-2">
            <p className="cp-text-label text-ink-subtle">Total</p>
            <p className="cp-text-stat-xl tnum text-ink">{invoice.total !== null ? money(invoice.total, invoice.currency ?? "EUR") : "–"}</p>
            <p className="cp-text-meta tnum text-ink-subtle">{invoice.currency ?? "Currency not read"}</p>
          </div>
          <div className="flex items-center gap-8">
            {invoice.status === "FAILED" ? (
              <ActionButton label="Retry" icon="retry" hint="Run the pipeline again from the start." disabledReason={null} onClick={() => setAction("retry")} />
            ) : null}
            {stale ? (
              <ActionButton
                label="Reassess"
                icon="refresh"
                hint="Fields were corrected after validation."
                disabledReason={null}
                onClick={() => setAction("reassess")}
              />
            ) : null}
            <ActionButton label="Reject" icon="ban" variant="danger" disabledReason={decide} onClick={() => setAction("reject")} />
            <ActionButton
              label="Escalate"
              icon="arrow-up-right"
              disabledReason={!inReview ? notInReview : seniorQueue ? "Already in a senior queue." : null}
              onClick={() => setAction("escalate")}
            />
            <ActionButton label="Request information" icon="help-circle" disabledReason={decide} onClick={() => setAction("request-info")} />
            <ActionButton
              label="Approve"
              icon={seniorOnly ? "lock" : "check"}
              variant="approve"
              disabledReason={decide ?? (stale ? "Reassess first: fields were corrected after validation." : null)}
              onClick={() => setAction("approve")}
            />
          </div>
        </div>
      </div>

      {invoice.error || running || error || stale || refused || invoice.export?.note ? (
        <div className="flex flex-col gap-8 px-24 py-10 hairline-b">
          {invoice.error ? (
            <Alert tone="danger">
              <Tooltip content={firstLine(invoice.error, 800)} className="w-full">
                <span className="block truncate">{firstLine(invoice.error, 200)}</span>
              </Tooltip>
            </Alert>
          ) : null}
          {stale ? <Alert tone="warning">Fields were corrected. Reassess before approving.</Alert> : null}
          {refused ? (
            <Alert tone="danger">
              The ERP refused the export.{" "}
              {exportErrors.map((e) => `${e.rule}${e.field ? ` (${e.field})` : ""}: ${e.message}`).join("; ")}. Correct the fields,
              reassess and approve again.
            </Alert>
          ) : null}
          {invoice.export?.note && !refused ? <Alert tone="info">Export: {invoice.export.note}</Alert> : null}
          {running ? (
            <Alert tone="info">
              {exporting
                ? "Approved. The export to the ERP is running; this page reloads every 10 seconds."
                : "The pipeline is still working on this invoice. This page reloads every 10 seconds."}
            </Alert>
          ) : null}
          {error ? <Alert tone="warning">Reload failed: {error}</Alert> : null}
        </div>
      ) : null}

      <CaseActionDialog
        reference={invoice.reference}
        action={action}
        consequence={action ? consequence(action, invoice) : undefined}
        done={{ reassess: "sent back for validation" }}
        run={(a, note) => api.actInvoice(invoice.id, a, invoice.version, note)}
        onClose={() => setAction(null)}
        onDone={() => {
          setAction(null);
          onChanged();
        }}
      />
    </header>
  );
}
