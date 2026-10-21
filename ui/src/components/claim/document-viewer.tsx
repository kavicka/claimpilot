"use client";

import { Alert, EmptyState, IconButton, Tooltip, useSwapDirection } from "@crm-ui/react";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { cn } from "@/lib/cn";
import { docTypeLabel } from "@/lib/enums";
import type { BBox, ClaimDocument, Field } from "@/lib/types";

import type { Selection } from "./claim-view";
import { fieldLabel } from "./field-utils";

const ZOOMS = [1, 1.25, 1.5, 2];
const PAD = 0.004;

export function boxStyle(b: BBox): React.CSSProperties {
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
  // Another document: its pages rise in, so the switch reads as a new document, not a glitch.
  const docSwap = useSwapDirection(doc ? documents.indexOf(doc) : -1);

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
        <EmptyState icon="file-remove" title="This claim has no documents." />
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
    <section className="flex min-h-0 flex-col bg-surface-tabs">
      <div className="flex items-center gap-12 bg-surface px-16 py-8 hairline-b">
        {/* Documents as a pill tab track (DF 2:33), with the file name under each type */}
        <div role="tablist" aria-label="Documents" className="cp-tabs flex min-w-0 flex-1 flex-wrap">
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
                  "cp-tab h-auto flex-col items-start gap-2 py-4 text-left transition-[background-color,box-shadow,color] duration-(--cp-dur-2)",
                  active && "bg-surface",
                )}
              >
                <span>{docTypeLabel(d.doc_type)}</span>
                <span className="cp-text-meta text-ink-subtle">{d.filename}</span>
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-12">
          <Tooltip content={showAll ? "Hide field boxes" : "Show every field box on the page"} side="bottom">
            <IconButton
              variant="toolbar"
              icon="bounding-box"
              iconSize={20}
              aria-pressed={showAll}
              label="Show all field boxes"
              onClick={() => setShowAll((v) => !v)}
              className={cn(showAll && "text-accent")}
            />
          </Tooltip>
          <Tooltip content="Zoom out" side="bottom">
            <IconButton
              variant="toolbar"
              icon="minus"
              iconSize={20}
              label="Zoom out"
              disabled={zoomIndex === 0}
              onClick={() => setZoomIndex((z) => Math.max(0, z - 1))}
              className="disabled:opacity-40"
            />
          </Tooltip>
          <span className="cp-text-label tnum w-[2.75rem] text-center text-ink-cell">{Math.round(zoom * 100)} %</span>
          <Tooltip content="Zoom in" side="bottom">
            <IconButton
              variant="toolbar"
              icon="plus-lg"
              iconSize={20}
              label="Zoom in"
              disabled={zoomIndex === ZOOMS.length - 1}
              onClick={() => setZoomIndex((z) => Math.min(ZOOMS.length - 1, z + 1))}
              className="disabled:opacity-40"
            />
          </Tooltip>
        </div>
      </div>

      {notice ? (
        <Alert tone="warning" className="rounded-none">
          {notice}
        </Alert>
      ) : null}

      <div
        ref={scroller}
        tabIndex={0} // keyboard users scroll the pages with the arrow keys
        role="region"
        aria-label="Document pages"
        className="viewer-bg pane-scroll relative min-h-0 flex-1 overflow-auto focus-visible:-outline-offset-2"
      >
        {doc.pages.length === 0 ? (
          <EmptyState icon="image-off" title="No page images for this document." />
        ) : (
          <div key={doc.id} className={cn("flex flex-col items-center gap-20 px-16 py-20", docSwap && "cp-swap-up")} style={{ width: zoom > 1 ? `${zoom * 100}%` : undefined }}>
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
                <div key={src} className="w-full max-w-[56.25rem]" style={zoom > 1 ? { maxWidth: "none" } : undefined}>
                  <div className="cp-text-meta mb-6 flex items-center justify-between text-ink-subtle">
                    <span>
                      Page {n} of {doc.pages.length}
                    </span>
                    {i === 0 && doc.language ? <span className="uppercase">{doc.language}</span> : null}
                  </div>
                  <div
                    data-page={n}
                    className="relative overflow-hidden rounded-(--radius-4) bg-surface shadow-(--shadow-panel) hairline"
                  >
                    {broken[src] ? (
                      <div className="flex aspect-[1/1.414] items-center justify-center">
                        <EmptyState icon="image-off" title="Page image could not be loaded." />
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
                        className="absolute rounded-(--radius-2) bg-accent-track/40 shadow-[inset_0_0_0_var(--stroke-1)_var(--accent)] opacity-70 transition-opacity duration-(--cp-dur-1) hover:opacity-100"
                      />
                    ))}
                    {highlight ? (
                      <div key={`${highlight.id}-${selection?.nonce}`} className="pointer-events-none absolute" style={boxStyle(highlight.bbox!)}>
                        <div className="absolute inset-0 animate-mark rounded-(--radius-2) bg-accent-track shadow-[inset_0_0_0_var(--stroke-focus)_var(--accent)]" />
                        <span
                          className={cn(
                            "cp-text-meta absolute left-0 whitespace-nowrap rounded-(--radius-4) bg-surface-dark px-6 py-2 text-ink-on-dark-soft shadow-(--shadow-coachmark)",
                            highlight.bbox!.y0 < 0.04 ? "top-full mt-4" : "bottom-full mb-4",
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
