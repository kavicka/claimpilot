"use client";

import { DetailCard, EmptyState, Icon, Tag, type LineItemColumn } from "@crm-ui/react";

import { PanelSection } from "@/components/claim/routing-panel";
import { INVOICE_RULE, failedCheckLabel, findingLabel, statusEntry } from "@/lib/enums";
import type { Field, InvoiceDetail, ValidationCheck } from "@/lib/types";

import { fieldByPath, pathLabel } from "./invoice-utils";

export function ChecksPanel({
  invoice,
  columns,
  onSelectField,
  onSelectLine,
}: {
  invoice: InvoiceDetail;
  columns: LineItemColumn[];
  onSelectField: (field: Field) => void;
  onSelectLine: (n: number) => void;
}) {
  const failed = invoice.validation.filter((c) => !c.ok);
  const passed = invoice.validation.filter((c) => c.ok);
  const matching = invoice.matching;

  function fieldLinks(check: ValidationCheck) {
    if (check.fields.length === 0) return null;
    return (
      <span className="flex flex-wrap gap-x-10 gap-y-2">
        {check.fields.map((path) => {
          const field = fieldByPath(invoice, path);
          const label = pathLabel(path, columns);
          return field ? (
            <button
              key={path}
              type="button"
              onClick={() => onSelectField(field)}
              className="cp-text-label-regular text-link underline underline-offset-2"
            >
              {label}
            </button>
          ) : (
            <span key={path} className="cp-text-label-regular text-ink-subtle">
              {label}
            </span>
          );
        })}
      </span>
    );
  }

  return (
    <div>
      <PanelSection title={`Validation (${failed.length} failed, ${passed.length} passed)`}>
        {invoice.validation.length === 0 ? (
          <p className="cp-text-cell text-ink-subtle">
            Not validated yet. Status now: {statusEntry(invoice.status).label}.
          </p>
        ) : (
          <>
            {failed.length === 0 ? <p className="cp-text-cell text-ink-cell">Every check passed.</p> : null}
            <ul className="flex flex-col gap-10">
              {failed.map((c, i) => (
                <li key={`${c.name}-${i}`} className="flex flex-col gap-4">
                  <span className="flex flex-wrap items-center gap-8">
                    <Tag tone="danger" icon="close" size="md">
                      {failedCheckLabel(c.name)}
                    </Tag>
                    {c.detail ? <span className="cp-text-cell text-ink-cell">{c.detail}</span> : null}
                  </span>
                  {fieldLinks(c)}
                </li>
              ))}
            </ul>
            {passed.length ? (
              <details className="group">
                <summary className="cp-text-label flex cursor-pointer items-center gap-6 text-ink-subtle">
                  <Icon name="caret-right" size={12} className="transition-transform duration-(--cp-dur-1) group-open:rotate-90" />
                  {passed.length} {passed.length === 1 ? "check" : "checks"} passed
                </summary>
                <ul className="mt-8 flex flex-col gap-6">
                  {passed.map((c, i) => (
                    <li key={`${c.name}-${i}`} className="flex flex-wrap items-center gap-8">
                      <Tag tone="success" icon="check" size="md">
                        {c.name}
                      </Tag>
                      {fieldLinks(c)}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        )}
      </PanelSection>

      <PanelSection title={`ERP matching${matching ? ` (${matching.findings.length} findings)` : ""}`}>
        {!matching ? (
          <p className="cp-text-cell text-ink-subtle">Not matched yet.</p>
        ) : (
          <>
            <DetailCard
              rows={[
                { label: "Supplier in the ERP", value: matching.supplier ?? <span className="text-ink-subtle">Not found</span> },
                { label: "Order", value: matching.order ?? <span className="text-ink-subtle">Not found</span> },
              ]}
            />
            {matching.findings.length === 0 ? (
              <p className="cp-text-cell text-ink-cell">Every line matches the order and the goods receipt.</p>
            ) : (
              <ul className="flex flex-col gap-8">
                {matching.findings.map((f, i) => {
                  const line = f.line === null || f.line === undefined ? null : invoice.lines[f.line] ?? null;
                  return (
                    <li key={`${f.kind}-${i}`} className="flex flex-wrap items-center gap-8">
                      <Tag tone="warning" icon="warning" size="md">
                        {findingLabel(f.kind)}
                      </Tag>
                      {line ? (
                        <button
                          type="button"
                          onClick={() => onSelectLine(line.n)}
                          className="cp-text-label text-link underline underline-offset-2"
                        >
                          Line {line.n}
                        </button>
                      ) : f.line !== null && f.line !== undefined ? (
                        <span className="cp-text-label text-ink-subtle">Line {f.line + 1}</span>
                      ) : null}
                      {f.detail ? <span className="cp-text-cell text-ink-cell">{f.detail}</span> : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </PanelSection>

      <PanelSection title={`Routing (${invoice.routing.length} rules)`}>
        {invoice.routing.length === 0 ? (
          <EmptyState icon="route" title={invoice.queue ? "No rules fired." : "Not routed yet."} />
        ) : (
          <ul className="flex flex-col gap-8">
            {invoice.routing.map((h, i) => (
              <li key={`${h.rule}-${i}`} className="flex items-start gap-10">
                <Tag tone="neutral" size="md">
                  {h.rule}
                </Tag>
                <span className="flex flex-col gap-2 pt-2">
                  <span className="cp-text-cell text-ink-cell">{INVOICE_RULE[h.rule] ?? h.rule}</span>
                  {h.detail ? <span className="cp-text-label-regular font-num text-ink-subtle">{h.detail}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </PanelSection>
    </div>
  );
}
