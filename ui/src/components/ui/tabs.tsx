"use client";

import { cn } from "@/lib/cn";

export interface TabItem<K extends string> {
  key: K;
  label: React.ReactNode;
  count?: number;
  /** Small coloured marker after the label (warnings, errors). */
  flag?: "warning" | "danger";
  title?: string;
}

/** Pill tab strip (w-fit, scrolls horizontally when narrow). */
export function PillTabs<K extends string>({
  tabs,
  value,
  onChange,
  label,
  className,
}: {
  tabs: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  className?: string;
}) {
  return (
    <div className={cn("pane-scroll overflow-x-auto", className)}>
      <div role="tablist" aria-label={label} className="flex w-fit gap-1 rounded-xl bg-stone-100 p-1">
        {tabs.map((t) => {
          const active = t.key === value;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              title={t.title}
              onClick={() => onChange(t.key)}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition",
                active ? "bg-sheet text-ink shadow-sm ring-1 ring-black/5" : "text-ink-2 hover:text-ink",
              )}
            >
              {t.label}
              {t.count !== undefined ? (
                <span
                  className={cn(
                    "tnum min-w-5 rounded-md px-1 text-center text-[11px] leading-[18px]",
                    active ? "bg-stone-100 text-ink" : "bg-black/[0.05] text-ink-3",
                  )}
                >
                  {t.count}
                </span>
              ) : null}
              {t.flag ? (
                <span
                  aria-hidden
                  className={cn("size-1.5 rounded-full", t.flag === "danger" ? "bg-red-500" : "bg-amber-500")}
                />
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Underline tabs for panels inside a sheet. */
export function LineTabs<K extends string>({
  tabs,
  value,
  onChange,
  label,
  className,
  trailing,
}: {
  tabs: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  className?: string;
  trailing?: React.ReactNode;
}) {
  return (
    <div className={cn("flex items-end gap-3 border-b border-line", className)}>
      <div role="tablist" aria-label={label} className="pane-scroll -mb-px flex min-w-0 flex-1 gap-4 overflow-x-auto">
        {tabs.map((t) => {
          const active = t.key === value;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              title={t.title}
              onClick={() => onChange(t.key)}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap border-b-2 pb-2.5 pt-1 text-[13px] font-medium transition",
                active ? "border-ink text-ink" : "border-transparent text-ink-3 hover:text-ink",
              )}
            >
              {t.label}
              {t.count !== undefined ? <span className="tnum text-[11px] text-ink-3">{t.count}</span> : null}
              {t.flag ? (
                <span
                  aria-hidden
                  className={cn("size-1.5 rounded-full", t.flag === "danger" ? "bg-red-500" : "bg-amber-500")}
                />
              ) : null}
            </button>
          );
        })}
      </div>
      {trailing ? <div className="shrink-0 pb-2">{trailing}</div> : null}
    </div>
  );
}
