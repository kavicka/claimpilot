"use client";

import { EmptyState, LineItemTable, type LineItemColumn } from "@claimpilot/ui";
import { useMemo } from "react";

import { api, errorMessage } from "@/lib/api";
import { statusEntry } from "@/lib/enums";
import type { Field, FieldPatchResult, InvoiceDetail } from "@/lib/types";

import { lineItems } from "./invoice-utils";

export function LinesPanel({
  invoice,
  columns,
  selectedFieldId,
  selectedLine,
  editable,
  onSelectField,
  onSelectLine,
  onHoverLine,
  onSaved,
}: {
  invoice: InvoiceDetail;
  columns: LineItemColumn[];
  selectedFieldId: number | null;
  selectedLine: number | null;
  editable: boolean;
  onSelectField: (field: Field) => void;
  onSelectLine: (n: number) => void;
  onHoverLine: (n: number | null) => void;
  onSaved: (result: FieldPatchResult) => void;
}) {
  const rows = useMemo(() => lineItems(invoice, columns), [invoice, columns]);
  const flagged = rows.filter((r) => (r.flags?.length ?? 0) > 0 || Object.values(r.cells).some((c) => c?.flags?.length)).length;

  function fieldOf(n: string, key: string): Field | null {
    return invoice.lines.find((l) => String(l.n) === n)?.fields[key] ?? null;
  }

  if (invoice.lines.length === 0) {
    return (
      <EmptyState
        icon="list-dash"
        title="No lines yet."
        description={`Lines appear after extraction. Status now: ${statusEntry(invoice.status).label}.`}
      />
    );
  }

  return (
    <div className="flex flex-col gap-12 px-20 py-16">
      <p className="cp-text-label-regular text-ink-subtle">
        <span className="tnum">{rows.length}</span> {rows.length === 1 ? "line" : "lines"}
        {flagged ? (
          <>
            {" · "}
            <span className="tnum text-danger-ink">{flagged}</span> with problems
          </>
        ) : null}
        {editable ? " · Values as printed. Double-click a cell to correct it." : " · Values as printed."}
      </p>
      {!editable ? (
        <p className="cp-text-label-regular rounded-(--radius-8) bg-surface-subtle px-12 py-8 text-ink-subtle">
          Lines can be corrected while the invoice is in review. Status now: {statusEntry(invoice.status).label}.
        </p>
      ) : null}
      <LineItemTable
        label="Invoice lines"
        columns={columns}
        rows={rows}
        selectedCell={selectedFieldId === null ? null : String(selectedFieldId)}
        selectedRow={selectedLine === null ? null : String(selectedLine)}
        onSelectCell={(row, column) => {
          const f = fieldOf(row.key, column.key);
          if (f) onSelectField(f);
        }}
        onSelectRow={(row) => onSelectLine(Number(row.key))}
        onHoverRow={(row) => onHoverLine(row ? Number(row.key) : null)}
        editable={editable}
        onEditCell={async (row, column, _cell, value) => {
          const f = fieldOf(row.key, column.key);
          if (!f) return;
          try {
            onSaved(await api.patchField(f.id, value, invoice.version));
          } catch (err) {
            throw new Error(errorMessage(err));
          }
        }}
      />
    </div>
  );
}
