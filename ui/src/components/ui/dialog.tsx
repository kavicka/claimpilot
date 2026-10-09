"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/cn";

/** Native <dialog> as a modal: focus trap, Esc and backdrop click close it. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  className,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "m-auto w-[min(520px,calc(100vw-32px))] rounded-2xl border border-line bg-sheet p-0 text-ink shadow-[0_24px_80px_rgb(0_0_0/0.25)] open:animate-rise",
        className,
      )}
    >
      {open ? (
        <div className="flex max-h-[80vh] flex-col">
          <div className="flex items-start gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold leading-snug">{title}</h2>
              {description ? <p className="mt-1 text-sm text-ink-2">{description}</p> : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-mr-1 rounded-md p-1 text-ink-3 transition hover:bg-stone-100 hover:text-ink"
            >
              <X className="size-4" />
            </button>
          </div>
          {children ? <div className="pane-scroll overflow-y-auto px-5 py-4">{children}</div> : null}
          {footer ? (
            <div className="flex items-center justify-end gap-2 border-t border-line bg-stone-50/60 px-5 py-3">
              {footer}
            </div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
