"use client";

import { Checkbox, EmptyState } from "@crm-ui/react";
import { useEffect, useState } from "react";

import { DOT, FieldRow, Legend } from "@/components/claim/field-panel";
import { isFlagged } from "@/components/claim/field-utils";
import { statusEntry } from "@/lib/enums";
import type { Field, FieldPatchResult, InvoiceDetail } from "@/lib/types";

import { groupHeader } from "./invoice-utils";

export function HeaderPanel({
  invoice,
  selectedFieldId,
  editable,
  onSelect,
  onSaved,
}: {
  invoice: InvoiceDetail;
  selectedFieldId: number | null;
  editable: boolean;
  onSelect: (field: Field) => void;
  onSaved: (result: FieldPatchResult) => void;
}) {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const flaggedTotal = invoice.header.filter(isFlagged).length;

  useEffect(() => {
    if (selectedFieldId === null) return;
    document.getElementById(`field-${selectedFieldId}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedFieldId]);

  if (invoice.header.length === 0) {
    return (
      <EmptyState
        icon="search-remove"
        title="No header fields yet."
        description={`Fields appear after extraction. Status now: ${statusEntry(invoice.status).label}.`}
      />
    );
  }

  const groups = groupHeader(onlyFlagged ? invoice.header.filter(isFlagged) : invoice.header);

  return (
    <div className="pb-32">
      <div className="flex flex-wrap items-center gap-x-16 gap-y-8 px-20 py-10 hairline-b">
        <Checkbox variant="table" checked={onlyFlagged} onCheckedChange={setOnlyFlagged}>
          Only fields to check <span className="tnum text-ink-subtle">({flaggedTotal})</span>
        </Checkbox>
        <span className="cp-text-meta ml-auto flex items-center gap-12 text-ink-subtle">
          <Legend className={DOT.high} label="≥ 0.9" />
          <Legend className={DOT.medium} label="0.7–0.9" />
          <Legend className={DOT.low} label="< 0.7" />
          <Legend className={DOT.empty} label="no value" />
        </span>
      </div>
      {!editable ? (
        <p className="cp-text-label-regular bg-surface-subtle px-20 py-8 text-ink-subtle hairline-b">
          Fields can be corrected while the invoice is in review. Status now: {statusEntry(invoice.status).label}.
        </p>
      ) : null}
      {groups.length === 0 ? <p className="cp-text-label-regular px-20 py-12 text-ink-subtle">Nothing to check in the header.</p> : null}
      {groups.map((g) => (
        <section key={g.key} aria-labelledby={`group-${g.key}`}>
          <h3 id={`group-${g.key}`} className="cp-text-tab sticky top-0 z-10 bg-surface-header px-20 py-8 text-ink hairline-b">
            {g.title}
          </h3>
          {g.fields.map(({ field, label }) => (
            <FieldRow
              key={field.id}
              field={field}
              label={label}
              indent={false}
              selected={field.id === selectedFieldId}
              editable={editable}
              claimVersion={invoice.version}
              onSelect={() => onSelect(field)}
              onSaved={onSaved}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
