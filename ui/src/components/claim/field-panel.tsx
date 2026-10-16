"use client";

import { Checkbox, EmptyState, IconButton, Tag, Tooltip } from "@claimpilot/ui";
import { useEffect, useRef, useState } from "react";

import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { docTypeLabel, failedCheckLabel, statusEntry } from "@/lib/enums";
import type { ClaimDocument, ClaimStatus, Field, FieldPatchResult } from "@/lib/types";

import { confidenceLevel, failedChecks, groupFields, isFlagged, type Level } from "./field-utils";

export const DOT: Record<Level, string> = {
  high: "bg-status-online",
  medium: "bg-marker-comment",
  low: "bg-danger-swipe",
  empty: "bg-icon-caret",
  unknown: "bg-icon-caret",
};

function dotTip(f: Field, level: Level): string {
  if (level === "empty") return "No value found";
  if (level === "unknown") return "No confidence score";
  return `Confidence ${f.confidence!.toFixed(2)}`;
}

export function FieldPanel({
  documents,
  activeDocId,
  selectedFieldId,
  editable,
  status,
  claimVersion,
  onSelect,
  onShowDocument,
  onSaved,
}: {
  claimVersion: number;
  documents: ClaimDocument[];
  activeDocId: string | null;
  selectedFieldId: number | null;
  editable: boolean;
  status: ClaimStatus;
  onSelect: (field: Field, docId: string) => void;
  onShowDocument: (docId: string) => void;
  onSaved: (result: FieldPatchResult) => void;
}) {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const flaggedTotal = documents.reduce((n, d) => n + d.fields.filter(isFlagged).length, 0);

  // Keep the selected row visible when the selection comes from the document viewer.
  useEffect(() => {
    if (selectedFieldId === null) return;
    document.getElementById(`field-${selectedFieldId}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedFieldId]);

  if (documents.length === 0) {
    return <EmptyState icon="search-remove" title="No documents, so no fields." />;
  }

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
          Fields can be corrected while the claim is in review. Status now: {statusEntry(status).label}.
        </p>
      ) : null}

      {documents.map((doc) => {
        const groups = groupFields(onlyFlagged ? doc.fields.filter(isFlagged) : doc.fields);
        const flagged = doc.fields.filter(isFlagged).length;
        const active = doc.id === activeDocId;
        return (
          <section key={doc.id} aria-label={docTypeLabel(doc.doc_type)}>
            <button
              type="button"
              onClick={() => onShowDocument(doc.id)}
              aria-current={active || undefined}
              className={cn(
                "sticky top-0 z-10 flex w-full items-center gap-8 px-20 py-8 text-left hairline-b transition-colors duration-(--cp-dur-1)",
                active ? "bg-accent-soft" : "bg-surface-header hover:bg-surface-subtle",
              )}
            >
              <span className="cp-text-tab text-ink">{docTypeLabel(doc.doc_type)}</span>
              <span className={cn("cp-text-meta truncate", active ? "text-ink-secondary" : "text-ink-subtle")}>{doc.filename}</span>
              <span className={cn("cp-text-meta ml-auto flex shrink-0 items-center gap-8", active ? "text-ink-secondary" : "text-ink-subtle")}>
                {flagged ? <span className="text-warning-ink">{flagged} to check</span> : null}
                <span className="tnum">{doc.fields.length} fields</span>
              </span>
            </button>
            {groups.length === 0 ? (
              <p className="cp-text-label-regular px-20 py-12 text-ink-subtle">
                {onlyFlagged ? "Nothing to check in this document." : "No fields extracted from this document."}
              </p>
            ) : (
              groups.map((g) => (
                <div key={g.key}>
                  {g.title ? (
                    <p className="cp-text-label px-20 pb-4 pt-12 text-ink-subtle">{g.title}</p>
                  ) : null}
                  {g.fields.map(({ field, label }) => (
                    <FieldRow
                      key={field.id}
                      field={field}
                      label={label}
                      indent={g.title !== null}
                      selected={field.id === selectedFieldId}
                      editable={editable}
                      claimVersion={claimVersion}
                      onSelect={() => onSelect(field, doc.id)}
                      onSaved={onSaved}
                    />
                  ))}
                </div>
              ))
            )}
          </section>
        );
      })}
    </div>
  );
}

export function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-4">
      <span className={cn("size-8 rounded-(--radius-pill)", className)} aria-hidden />
      {label}
    </span>
  );
}

export function FieldRow({
  field,
  label,
  indent,
  selected,
  editable,
  claimVersion,
  onSelect,
  onSaved,
}: {
  field: Field;
  label: string;
  indent: boolean;
  selected: boolean;
  editable: boolean;
  claimVersion: number;
  onSelect: () => void;
  onSaved: (result: FieldPatchResult) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const level = confidenceLevel(field);
  const failed = failedChecks(field);
  const hasValue = field.value !== null && field.value !== "";
  const showNorm = hasValue && field.value_norm !== null && field.value_norm !== field.value;

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setDraft(field.value ?? "");
    setProblem(null);
    setEditing(true);
    onSelect();
    window.setTimeout(() => input.current?.select(), 0);
  }

  async function save() {
    if (draft === (field.value ?? "")) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      const res = await api.patchField(field.id, draft, claimVersion);
      onSaved(res);
      setEditing(false);
    } catch (err) {
      const msg = errorMessage(err);
      setProblem(msg.charAt(0).toUpperCase() + msg.slice(1));
    } finally {
      setSaving(false);
    }
  }

  return (
    // The whole row is a click target for the mouse; keyboard and screen readers use the label
    // button, so no interactive element sits inside another.
    <div
      id={`field-${field.id}`}
      onClick={() => !editing && onSelect()}
      className={cn(
        "group relative grid cursor-pointer grid-cols-[10px_minmax(110px,0.75fr)_minmax(0,1.5fr)_28px] items-start gap-x-12 py-8 pr-12 transition-colors duration-(--cp-dur-1)",
        indent ? "pl-28" : "pl-20",
        selected
          ? "bg-accent-soft shadow-[inset_var(--stroke-focus)_0_0_var(--accent)]"
          : "hover:bg-surface-subtle focus-within:bg-surface-subtle",
      )}
    >
      <Tooltip content={dotTip(field, level)} side="right" className="pt-4">
        <span role="img" className={cn("block size-10 rounded-(--radius-pill)", DOT[level])} aria-label={dotTip(field, level)} />
      </Tooltip>

      <Tooltip content={field.field} className="min-w-0">
        <button
          type="button"
          aria-pressed={selected}
          onClick={(e) => {
            e.stopPropagation();
            if (!editing) onSelect();
          }}
          className="cp-text-cell block w-full truncate text-left text-ink-subtle focus-visible:underline focus-visible:outline-none"
        >
          {label}
        </button>
      </Tooltip>

      <div className="flex min-w-0 flex-col gap-4">
        {editing ? (
          <div className="flex items-center gap-6" onClick={(e) => e.stopPropagation()}>
            <input
              ref={input}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              disabled={saving}
              aria-label={`New value for ${label}`}
              className="cp-input min-w-0 flex-1 bg-surface shadow-[inset_0_0_0_var(--stroke-1)_var(--accent)]"
            />
            <Tooltip content="Save (Enter)">
              <IconButton icon={saving ? "spinner" : "check"} iconSize={14} label="Save" onClick={save} disabled={saving} className={cn(saving && "[&_.cp-icon]:animate-[cp-spin_0.8s_linear_infinite]")} />
            </Tooltip>
            <Tooltip content="Cancel (Esc)">
              <IconButton icon="close" iconSize={14} label="Cancel" onClick={() => setEditing(false)} disabled={saving} />
            </Tooltip>
          </div>
        ) : hasValue ? (
          <p className="cp-text-tab whitespace-pre-wrap break-words text-ink-cell">
            {field.value}
            {showNorm ? <span className="cp-text-label-regular ml-6 text-ink-subtle">→ {field.value_norm}</span> : null}
          </p>
        ) : (
          <p className="cp-text-cell italic text-ink-subtle">Not found</p>
        )}

        {problem ? <p className="cp-field__error">{problem}</p> : null}

        {(!field.grounded && hasValue) || failed.length > 0 || field.corrected ? (
          <div className="flex flex-wrap gap-4">
            {field.corrected ? (
              <Tag tone="info" icon="pencil">
                Corrected
              </Tag>
            ) : null}
            {!field.grounded && hasValue ? (
              <Tooltip content="The value was not found in the document text.">
                <Tag tone="orange">Not grounded</Tag>
              </Tooltip>
            ) : null}
            {failed.map((name) => (
              <Tooltip key={name} content={`Check: ${name}`}>
                <Tag tone="danger" icon="close">
                  {failedCheckLabel(name)}
                </Tag>
              </Tooltip>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex justify-end">
        {editable && !editing ? (
          <Tooltip content="Correct value">
            <IconButton
              variant="bare"
              icon="pencil"
              iconSize={14}
              label={`Correct ${label}`}
              onClick={startEdit}
              className="p-4 text-ink-subtle opacity-0 transition-opacity duration-(--cp-dur-1) focus-visible:opacity-100 group-hover:opacity-100"
            />
          </Tooltip>
        ) : null}
      </div>
    </div>
  );
}
