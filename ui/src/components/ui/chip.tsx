import type { ComponentType, ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ChipVariant = "neutral" | "success" | "danger" | "info" | "warning" | "purple" | "orange";

const TINT: Record<ChipVariant, string> = {
  neutral: "bg-stone-100 text-stone-600 ring-stone-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  danger: "bg-red-50 text-red-700 ring-red-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  warning: "bg-amber-50 text-amber-800 ring-amber-200",
  purple: "bg-violet-50 text-violet-800 ring-violet-200",
  orange: "bg-orange-50 text-orange-800 ring-orange-200",
};

const DOT: Record<ChipVariant, string> = {
  neutral: "bg-stone-400",
  success: "bg-emerald-500",
  danger: "bg-red-500",
  info: "bg-sky-500",
  warning: "bg-amber-500",
  purple: "bg-violet-500",
  orange: "bg-orange-500",
};

export function Chip({
  variant = "neutral",
  icon: Icon,
  dot = false,
  mono = false,
  className,
  children,
}: {
  variant?: ChipVariant;
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Outlined pill with a small square colour dot (categories). */
  dot?: boolean;
  mono?: boolean;
  className?: string;
  children: ReactNode;
}) {
  if (dot) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-stone-300/80 bg-white px-2 py-0.5 text-xs font-medium text-ink",
          mono && "font-mono",
          className,
        )}
      >
        <span className={cn("size-2 shrink-0 rounded-[3px]", DOT[variant])} aria-hidden />
        {children}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TINT[variant],
        mono && "font-mono",
        className,
      )}
    >
      {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden /> : null}
      {children}
    </span>
  );
}
