"use client";

import { useCallback, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/cn";

type Side = "top" | "bottom" | "right";

/**
 * Hover/focus tooltip rendered in a portal with fixed positioning, so scroll panes and
 * overflow-hidden tables never clip it. Opens after a short delay.
 */
export function Tooltip({
  content,
  side = "top",
  delay = 250,
  className,
  children,
}: {
  content: React.ReactNode;
  side?: Side;
  delay?: number;
  className?: string;
  children: React.ReactNode;
}) {
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const show = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const r = ref.current?.getBoundingClientRect();
      if (!r) return;
      if (side === "right") setPos({ x: r.right + 8, y: r.top + r.height / 2 });
      else if (side === "bottom") setPos({ x: r.left + r.width / 2, y: r.bottom + 6 });
      else setPos({ x: r.left + r.width / 2, y: r.top - 6 });
    }, delay);
  }, [delay, side]);

  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    setPos(null);
  }, []);

  if (content === null || content === undefined || content === "") return <>{children}</>;

  return (
    <span
      ref={ref}
      className={cn("inline-flex max-w-full", className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      aria-describedby={pos ? id : undefined}
    >
      {children}
      {pos
        ? createPortal(
            <span
              id={id}
              role="tooltip"
              style={{ left: pos.x, top: pos.y }}
              className={cn(
                "pointer-events-none fixed z-[200] max-w-[340px] whitespace-pre-line break-words rounded-lg bg-neutral-900 px-2.5 py-1.5 text-xs leading-snug text-white shadow-lg",
                side === "top" && "-translate-x-1/2 -translate-y-full",
                side === "bottom" && "-translate-x-1/2",
                side === "right" && "-translate-y-1/2",
              )}
            >
              {content}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
