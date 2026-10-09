"use client";

import { FileX, ImageOff, Minus, Plus, ScanSearch } from "lucide-react";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { docTypeLabel } from "@/lib/enums";
import type { BBox, ClaimDocument, Field } from "@/lib/types";

import type { Selection } from "./claim-view";
import { fieldLabel } from "./field-utils";

const ZOOMS = [1, 1.25, 1.5, 2];
const PAD = 0.004;

function boxStyle(b: BBox): React.CSSProperties {
  const x0 = Math.max(0, b.x0 - PAD);
  const y0 = Math.max(0, b.y0 - PAD);
  const x1 = Math.min(1, b.x1 + PAD);
  const y1 = Math.min(1, b.y1 + PAD);
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  };
}

export function DocumentViewer({
  documents,
  activeDocId,
  onActiveDocChange,
  selection,
  selectedField,
  onSelectField,
}: {
  documents: ClaimDocument[];
  activeDocId: string | null;
  onActiveDocChange: (id: string) => void;
  selection: Selection | null;
  selectedField: Field | null;
  onSelectField: (field: Field, docId: string) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [zoomIndex, setZoomIndex] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [broken, setBroken] = useState<Record<string, true>>({});
  const doc = documents.find((d) => d.id === activeDocId) ?? documents[0] ?? null;
  const zoom = ZOOMS[zoomIndex] ?? 1;

  const target = selection && selectedField && doc && selection.docId === doc.id ? selectedField : null;

  // A different document starts at its first page.
  const docKey = doc?.id;
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0, left: 0 });
  }, [docKey]);

  // Scroll the selected field's box into view once its page image has a height. Runs on a new
  // click or zoom only, not when polling hands us a fresh copy of the same field.
  const scrollToTarget = useEffectEvent(() => {
    if (!target || !scroller.current || target.page === null) return;
    const container = scroller.current;
    const page = container.querySelector<HTMLElement>(`[data-page="${target.page}"]`);
    if (!page) return;
    const img = page.querySelector("img");
    const go = () => {
      const top = page.offsetTop + (target.bbox ? target.bbox.y0 * page.offsetHeight : 0);
      const left = page.offsetLeft + (target.bbox ? target.bbox.x0 * page.offsetWidth : 0);
      container.scrollTo({
        top: Math.max(0, top - container.clientHeight * 0.3),
        left: zoom > 1 ? Math.max(0, left - container.clientWidth * 0.15) : 0,
        behavior: "smooth",
      });
    };
    if (!img || (img.complete && img.naturalHeight > 0)) {
      go();
      return;
    }
    img.addEventListener("load", go, { once: true });
    return () => img.removeEventListener("load", go);
  });
  const nonce = selection?.nonce;
  useEffect(() => scrollToTarget(), [nonce, zoom]);

  if (!doc) {
    return (
      <section className="viewer-bg flex min-h-0 items-center justify-center">
        <EmptyState icon={FileX} title="This claim has no documents." compact />
      </section>
    );
  }

  const notice =
    target && target.page === null
      ? "This field has no position in the document."
      : target && !target.bbox
        ? `No box for this field. Showing page ${target.page}.`
        : null;

  return (
    <section className="flex min-h-0 flex-col bg-[#e6e4de]">
      <div className="flex items-center gap-2 border-b border-line bg-[#f3f1ec] px-3 py-2">
        <div role="tablist" aria-label="Documents" className="flex min-w-0 flex-1 flex-wrap gap-1">
          {documents.map((d) => {
            const active = d.id === doc.id;
            return (
              <button
                key={d.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onActiveDocChange(d.id)}
                className={cn(
                  "flex shrink-0 flex-col items-start rounded-lg px-2.5 py-1.5 text-left transition",
                  active ? "bg-sheet shadow-sm ring-1 ring-black/5" : "hover:bg-black/[0.04]",
                )}
              >
                <span className={cn("text-[12.5px] font-medium leading-tight", active ? "text-ink" : "text-ink-2")}>
                  {docTypeLabel(d.doc_type)}
                </span>
                <span className="font-mono text-[10.5px] leading-tight text-ink-3">{d.filename}</span>
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-1 self-start border-l border-line pl-2 pt-1">
          <Tooltip content={showAll ? "Hide field boxes" : "Show every field box on the page"} side="bottom">
            <button
              type="button"
              aria-pressed={showAll}
              aria-label="Show all field boxes"
              onClick={() => setShowAll((v) => !v)}
              className={cn(
                "rounded-md p-1.5 transition",
                showAll ? "bg-ink text-white" : "text-ink-2 hover:bg-black/5 hover:text-ink",
              )}
            >
              <ScanSearch className="size-4" />
            </button>
          </Tooltip>
          <Tooltip content="Zoom out" side="bottom">
            <button
              type="button"
              aria-label="Zoom out"
              disabled={zoomIndex === 0}
              onClick={() => setZoomIndex((z) => Math.max(0, z - 1))}
              className="rounded-md p-1.5 text-ink-2 transition hover:bg-black/5 hover:text-ink disabled:opacity-35"
            >
              <Minus className="size-4" />
            </button>
          </Tooltip>
          <span className="tnum w-11 text-center text-xs text-ink-2">{Math.round(zoom * 100)} %</span>
          <Tooltip content="Zoom in" side="bottom">
            <button
              type="button"
              aria-label="Zoom in"
              disabled={zoomIndex === ZOOMS.length - 1}
              onClick={() => setZoomIndex((z) => Math.min(ZOOMS.length - 1, z + 1))}
              className="rounded-md p-1.5 text-ink-2 transition hover:bg-black/5 hover:text-ink disabled:opacity-35"
            >
              <Plus className="size-4" />
            </button>
          </Tooltip>
        </div>
      </div>

      {notice ? (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-900">{notice}</div>
      ) : null}

      <div ref={scroller} className="viewer-bg pane-scroll relative min-h-0 flex-1 overflow-auto">
        {doc.pages.length === 0 ? (
          <EmptyState icon={ImageOff} title="No page images for this document." compact />
        ) : (
          <div className="flex flex-col items-center gap-5 px-4 py-5" style={{ width: zoom > 1 ? `${zoom * 100}%` : undefined }}>
            {doc.pages.map((src, i) => {
              const n = i + 1;
              const onPage = doc.fields.filter((f) => f.page === n && f.bbox);
              const seen = new Set<string>();
              const outlines = showAll
                ? onPage.filter((f) => {
                    const k = JSON.stringify(f.bbox);
                    if (seen.has(k)) return false;
                    seen.add(k);
                    return true;
                  })
                : [];
              const highlight = target && target.page === n && target.bbox ? target : null;
              return (
                <div key={src} className="w-full max-w-[900px]" style={zoom > 1 ? { maxWidth: "none" } : undefined}>
                  <div className="mb-1.5 flex items-center justify-between text-[11px] text-ink-3">
                    <span>
                      Page {n} of {doc.pages.length}
                    </span>
                    {i === 0 && doc.language ? <span className="font-mono uppercase">{doc.language}</span> : null}
                  </div>
                  <div
                    data-page={n}
                    className="relative overflow-hidden rounded-[3px] bg-white shadow-[0_1px_2px_rgb(0_0_0/0.08),0_8px_24px_rgb(0_0_0/0.08)]"
                  >
                    {broken[src] ? (
                      <div className="flex aspect-[1/1.414] items-center justify-center">
                        <EmptyState icon={ImageOff} title="Page image could not be loaded." compact />
                      </div>
                    ) : (
                      <img
                        src={src}
                        alt={`${docTypeLabel(doc.doc_type)}, page ${n}`}
                        draggable={false}
                        onError={() => setBroken((b) => ({ ...b, [src]: true }))}
                        className="block h-auto w-full select-none"
                      />
                    )}
                    {outlines.map((f) => (
                      <button
                        key={`o-${f.id}`}
                        type="button"
                        aria-label={`Select ${fieldLabel(f.field)}`}
                        title={fieldLabel(f.field)}
                        onClick={() => onSelectField(f, doc.id)}
                        style={boxStyle(f.bbox!)}
                        className="absolute rounded-[2px] border border-sky-500/60 bg-sky-400/[0.06] transition hover:border-sky-600 hover:bg-sky-400/15"
                      />
                    ))}
                    {highlight ? (
                      <div key={`${highlight.id}-${selection?.nonce}`} className="pointer-events-none absolute" style={boxStyle(highlight.bbox!)}>
                        <div className="absolute inset-0 animate-mark rounded-[3px] bg-marker/45 mix-blend-multiply" />
                        <div className="absolute inset-0 rounded-[3px] ring-2 ring-marker-edge" />
                        <span
                          className={cn(
                            "absolute left-0 whitespace-nowrap rounded bg-ink px-1.5 py-0.5 font-mono text-[10.5px] text-white shadow",
                            highlight.bbox!.y0 < 0.04 ? "top-full mt-1" : "bottom-full mb-1",
                          )}
                        >
                          {highlight.field}
                        </span>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
