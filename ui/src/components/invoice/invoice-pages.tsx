"use client";

import { Alert, EmptyState, IconButton, Tooltip } from "@claimpilot/ui";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { boxStyle } from "@/components/claim/document-viewer";
import { cn } from "@/lib/cn";
import type { BBox, InvoiceDocument } from "@/lib/types";

const ZOOMS = [1, 1.25, 1.5, 2];

export interface PageMark {
  key: string;
  page: number;
  bbox: BBox;
  /** select: the field or line in focus, with its name above the box; hover: a line under the pointer. */
  tone: "select" | "hover";
  label?: string;
}

export interface PageBox {
  key: string;
  page: number;
  bbox: BBox;
  label: string;
  onSelect: () => void;
}

/** The invoice's pages with boxes on them; scrolls to `target` whenever its nonce changes. */
export function InvoicePages({
  document: doc,
  marks,
  boxes,
  target,
  notice,
}: {
  document: InvoiceDocument | null;
  marks: PageMark[];
  /** Every known box, outlined when "Show all boxes" is on. */
  boxes: PageBox[];
  target: { page: number; bbox: BBox | null; nonce: number } | null;
  notice: string | null;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [zoomIndex, setZoomIndex] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [broken, setBroken] = useState<Record<string, true>>({});
  const zoom = ZOOMS[zoomIndex] ?? 1;

  const scrollToTarget = useEffectEvent(() => {
    if (!target || !scroller.current) return;
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
  const nonce = target?.nonce;
  useEffect(() => scrollToTarget(), [nonce, zoom]);

  if (!doc) {
    return (
      <section className="viewer-bg flex min-h-0 items-center justify-center">
        <EmptyState icon="file-remove" title="This invoice has no document." />
      </section>
    );
  }

  return (
    <section className="flex min-h-0 flex-col bg-surface-tabs">
      <div className="flex items-center gap-12 bg-surface px-16 py-8 hairline-b">
        <p className="cp-text-tab min-w-0 flex-1 truncate text-ink">{doc.filename}</p>
        <div className="flex shrink-0 items-center gap-12">
          <Tooltip content={showAll ? "Hide the boxes" : "Show every field and line box on the page"} side="bottom">
            <IconButton
              variant="toolbar"
              icon="bounding-box"
              iconSize={20}
              aria-pressed={showAll}
              label="Show all boxes"
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
          <EmptyState icon="image-off" title="No page images for this document yet." />
        ) : (
          <div className="flex flex-col items-center gap-20 px-16 py-20" style={{ width: zoom > 1 ? `${zoom * 100}%` : undefined }}>
            {doc.pages.map((src, i) => {
              const n = i + 1;
              const here = marks.filter((m) => m.page === n);
              return (
                <div key={src} className="w-full max-w-[56.25rem]" style={zoom > 1 ? { maxWidth: "none" } : undefined}>
                  <p className="cp-text-meta mb-6 text-ink-subtle">
                    Page {n} of {doc.pages.length}
                  </p>
                  <div data-page={n} className="relative overflow-hidden rounded-(--radius-4) bg-surface shadow-(--shadow-panel) hairline">
                    {broken[src] ? (
                      <div className="flex aspect-[1/1.414] items-center justify-center">
                        <EmptyState icon="image-off" title="Page image could not be loaded." />
                      </div>
                    ) : (
                      <img
                        src={src}
                        alt={`${doc.filename}, page ${n}`}
                        draggable={false}
                        onError={() => setBroken((b) => ({ ...b, [src]: true }))}
                        className="block h-auto w-full select-none"
                      />
                    )}
                    {showAll
                      ? boxes
                          .filter((b) => b.page === n)
                          .map((b) => (
                            <button
                              key={`o-${b.key}`}
                              type="button"
                              aria-label={`Select ${b.label}`}
                              title={b.label}
                              onClick={b.onSelect}
                              style={boxStyle(b.bbox)}
                              className="absolute rounded-(--radius-2) bg-accent-track/40 shadow-[inset_0_0_0_var(--stroke-1)_var(--accent)] opacity-70 transition-opacity duration-(--cp-dur-1) hover:opacity-100"
                            />
                          ))
                      : null}
                    {here.map((m) =>
                      m.tone === "hover" ? (
                        <div
                          key={m.key}
                          data-mark="hover"
                          className="pointer-events-none absolute rounded-(--radius-2) bg-accent-track/40 shadow-[inset_0_0_0_var(--stroke-1)_var(--accent)]"
                          style={boxStyle(m.bbox)}
                        />
                      ) : (
                        <div key={`${m.key}-${target?.nonce}`} data-mark="select" className="pointer-events-none absolute" style={boxStyle(m.bbox)}>
                          <div className="absolute inset-0 animate-mark rounded-(--radius-2) bg-accent-track shadow-[inset_0_0_0_var(--stroke-focus)_var(--accent)]" />
                          {m.label ? (
                            <span
                              className={cn(
                                "cp-text-meta absolute left-0 whitespace-nowrap rounded-(--radius-4) bg-surface-dark px-6 py-2 text-ink-on-dark-soft shadow-(--shadow-coachmark)",
                                m.bbox.y0 < 0.04 ? "top-full mt-4" : "bottom-full mb-4",
                              )}
                            >
                              {m.label}
                            </span>
                          ) : null}
                        </div>
                      ),
                    )}
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
