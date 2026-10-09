import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-1.5 px-4 py-8" : "gap-2 px-6 py-16",
        className,
      )}
    >
      {Icon ? (
        <div
          className={cn(
            "mb-1 flex items-center justify-center rounded-xl border border-line bg-stone-50 text-ink-3",
            compact ? "size-9" : "size-11",
          )}
        >
          <Icon className={compact ? "size-4" : "size-5"} aria-hidden />
        </div>
      ) : null}
      <p className={cn("font-medium text-ink", compact ? "text-sm" : "text-[15px]")}>{title}</p>
      {description ? <p className="max-w-sm text-sm text-ink-2">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md px-2 py-1 font-medium text-red-800 underline-offset-2 hover:underline"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
