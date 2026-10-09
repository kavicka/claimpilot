"use client";

import { Check, LoaderCircle, Pencil, PencilLine, SearchX, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { docTypeLabel, failedCheckLabel, statusEntry } from "@/lib/enums";
import type { ClaimDocument, ClaimStatus, Field, FieldPatchResult } from "@/lib/types";

import { confidenceLevel, failedChecks, groupFields, isFlagged, type Level } from "./field-utils";

const DOT: Record<Level, string> = {
  high: "bg-emerald-500",
  medium: "bg-amber-400",
  low: "bg-red-500",
  empty: "bg-stone-300",
  unknown: "bg-stone-300",
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
  onSelect,
  onShowDocument,
  onSaved,
}: {
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
    return <EmptyState icon={SearchX} title="No documents, so no fields." compact />;
  }

  return (
    <div className="pb-8">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-2.5 text-xs text-ink-2">
        <label className="flex cursor-pointer select-none items-center gap-2">
          <input
            type="checkbox"
            checked={onlyFlagged}
            onChange={(e) => setOnlyFlagged(e.target.checked)}
            className="size-3.5 accent-ink"
          />
          Only fields to check <span className="tnum text-ink-3">({flaggedTotal})</span>
        </label>
        <span className="ml-auto flex items-center gap-3 text-ink-3">
          <Legend className="bg-emerald-500" label="≥ 0.9" />
          <Legend className="bg-amber-400" label="0.7–0.9" />
          <Legend className="bg-red-500" label="< 0.7" />
          <Legend className="bg-stone-300" label="no value" />
        </span>
      </div>
      {!editable ? (
        <p className="border-b border-line bg-stone-50 px-5 py-2 text-xs text-ink-2">
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
              className={cn(
                "sticky top-0 z-10 flex w-full items-center gap-2 border-b border-line px-5 py-2 text-left backdrop-blur transition",
                active ? "bg-marker-soft/95" : "bg-sheet/95 hover:bg-stone-50/95",
              )}
            >
              <span className="text-[13px] font-semibold">{docTypeLabel(doc.doc_type)}</span>
              <span className="truncate font-mono text-[11px] text-ink-3">{doc.filename}</span>
              <span className="ml-auto flex shrink-0 items-center gap-2 text-[11px] text-ink-3">
                {flagged ? <span className="text-amber-700">{flagged} to check</span> : null}
                <span className="tnum">{doc.fields.length} fields</span>
              </span>
            </button>
            {groups.length === 0 ? (
              <p className="px-5 py-3 text-xs text-ink-3">
                {onlyFlagged ? "Nothing to check in this document." : "No fields extracted from this document."}
              </p>
            ) : (
              groups.map((g) => (
                <div key={g.key}>
                  {g.title ? (
                    <p className="px-5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{g.title}</p>
                  ) : null}
                  {g.fields.map(({ field, label }) => (
                    <FieldRow
                      key={field.id}
                      field={field}
                      label={label}
                      indent={g.title !== null}
                      selected={field.id === selectedFieldId}
                      editable={editable}
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

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={cn("size-2 rounded-full", className)} aria-hidden />
      {label}
    </span>
  );
}

function FieldRow({
  field,
  label,
  indent,
  selected,
  editable,
  onSelect,
  onSaved,
}: {
  field: Field;
  label: string;
  indent: boolean;
  selected: boolean;
  editable: boolean;
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
      const res = await api.patchField(field.id, draft);
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
    <div
      id={`field-${field.id}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => !editing && onSelect()}
      onKeyDown={(e) => {
        if (!editing && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "group relative grid cursor-pointer grid-cols-[10px_minmax(110px,0.75fr)_minmax(0,1.5fr)_28px] items-start gap-x-3 border-l-[3px] py-2 pr-3 transition-colors focus-visible:outline-none",
        indent ? "pl-7" : "pl-[17px]",
        selected ? "border-marker-edge bg-marker-soft" : "border-transparent hover:bg-stone-50 focus-visible:bg-stone-50",
      )}
    >
      <Tooltip content={dotTip(field, level)} side="right" className="pt-[5px]">
        <span className={cn("block size-2.5 rounded-full", DOT[level])} aria-label={dotTip(field, level)} />
      </Tooltip>

      <Tooltip content={field.field} className="min-w-0">
        <span className="block truncate pt-px text-[13px] text-ink-2">{label}</span>
      </Tooltip>

      <div className="min-w-0">
        {editing ? (
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
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
              className="h-7 min-w-0 flex-1 rounded-md border border-ink/30 bg-white px-2 text-[13px] outline-none focus:border-ink focus:ring-2 focus:ring-ink/10"
            />
            <Tooltip content="Save (Enter)">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                aria-label="Save"
                className="rounded-md bg-ink p-1 text-white transition hover:bg-neutral-800"
              >
                {saving ? <LoaderCircle className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
              </button>
            </Tooltip>
            <Tooltip content="Cancel (Esc)">
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={saving}
                aria-label="Cancel"
                className="rounded-md p-1 text-ink-3 transition hover:bg-black/5 hover:text-ink"
              >
                <X className="size-3.5" />
              </button>
            </Tooltip>
          </div>
        ) : hasValue ? (
          <p className="whitespace-pre-wrap break-words text-[13px] font-medium leading-snug">
            {field.value}
            {showNorm ? <span className="ml-1.5 font-mono text-[11.5px] font-normal text-ink-3">→ {field.value_norm}</span> : null}
          </p>
        ) : (
          <p className="text-[13px] italic text-ink-3">Not found</p>
        )}

        {problem ? <p className="mt-1 text-xs text-red-700">{problem}</p> : null}

        {(!field.grounded && hasValue) || failed.length > 0 || field.corrected ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {field.corrected ? (
              <Chip variant="info" icon={PencilLine}>
                Corrected
              </Chip>
            ) : null}
            {!field.grounded && hasValue ? (
              <Tooltip content="The value was not found in the document text.">
                <Chip variant="orange">Not grounded</Chip>
              </Tooltip>
            ) : null}
            {failed.map((name) => (
              <Tooltip key={name} content={`Check: ${name}`}>
                <Chip variant="danger" icon={X}>
                  {failedCheckLabel(name)}
                </Chip>
              </Tooltip>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex justify-end">
        {editable && !editing ? (
          <Tooltip content="Correct value">
            <button
              type="button"
              onClick={startEdit}
              aria-label={`Correct ${label}`}
              className="rounded-md p-1 text-ink-3 opacity-0 transition hover:bg-black/5 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
            >
              <Pencil className="size-3.5" />
            </button>
          </Tooltip>
        ) : null}
      </div>
    </div>
  );
}
