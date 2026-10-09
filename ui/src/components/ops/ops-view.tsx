"use client";

import { CircleCheck, LoaderCircle, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Chip } from "@/components/ui/chip";
import { EmptyState, ErrorNote } from "@/components/ui/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { QUEUES, STATUS_ORDER, queueEntry, statusEntry } from "@/lib/enums";
import { firstLine, int, percent, seconds } from "@/lib/format";
import type { Ops } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

const BAR: Record<string, string> = {
  success: "bg-emerald-500",
  info: "bg-sky-500",
  purple: "bg-violet-500",
  danger: "bg-red-500",
  warning: "bg-amber-500",
  orange: "bg-orange-500",
  neutral: "bg-stone-400",
};

function Stat({ label, value, hint, delay }: { label: string; value: string; hint?: string; delay: number }) {
  return (
    <div
      className="animate-rise rounded-2xl border border-line bg-sheet px-5 py-4 shadow-[0_1px_2px_rgb(0_0_0/0.03)]"
      style={{ animationDelay: `${delay}ms` }}
    >
      <p className="text-[12px] font-medium text-ink-2">{label}</p>
      <p className="tnum mt-1.5 text-[28px] font-semibold leading-none tracking-tight">{value}</p>
      {hint ? <p className="mt-2 text-xs text-ink-3">{hint}</p> : null}
    </div>
  );
}

function Bars({ rows, total }: { rows: { key: string; label: string; variant: string; count: number }[]; total: number }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[120px_1fr_36px] items-center gap-3 text-[13px]">
          <span className="truncate text-ink-2">{r.label}</span>
          <span className="h-2 overflow-hidden rounded-full bg-stone-100">
            <span
              className={cn("block h-full rounded-full transition-[width] duration-500", BAR[r.variant] ?? BAR.neutral)}
              style={{ width: total ? `${(r.count / total) * 100}%` : 0 }}
            />
          </span>
          <span className="tnum text-right font-medium">{r.count}</span>
        </li>
      ))}
    </ul>
  );
}

function Card({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-2xl border border-line bg-sheet px-5 py-4 shadow-[0_1px_2px_rgb(0_0_0/0.03)]", className)}>
      <h2 className="mb-4 text-[13px] font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function queueRows(ops: Ops) {
  const keys = [...QUEUES, ...Object.keys(ops.by_queue).filter((k) => !(QUEUES as readonly string[]).includes(k))];
  return keys.map((k) => {
    const e = queueEntry(k);
    return { key: k, label: e?.label ?? "Not routed", variant: e?.variant ?? "neutral", count: ops.by_queue[k] ?? 0 };
  });
}

function statusRows(ops: Ops) {
  const known = STATUS_ORDER.filter((s) => ops.by_status[s]);
  const extra = Object.keys(ops.by_status).filter((s) => !(STATUS_ORDER as string[]).includes(s));
  return [...known, ...extra].map((s) => {
    const e = statusEntry(s);
    return { key: s, label: e.label, variant: e.variant, count: ops.by_status[s] ?? 0 };
  });
}

export function OpsView() {
  const { data: ops, error, loading, reload } = useFetch("ops", api.ops, { pollMs: 30000 });

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-7">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Ops</h1>
          <p className="mt-0.5 text-sm text-ink-2">Throughput, latency and failures across all claims.</p>
        </div>
        <Tooltip content="Reload now. The page also refreshes every 30 seconds." side="bottom">
          <button
            type="button"
            onClick={reload}
            aria-label="Reload"
            className="rounded-lg border border-line-2 bg-sheet p-2 text-ink-2 transition hover:text-ink"
          >
            <RefreshCw className="size-4" />
          </button>
        </Tooltip>
      </header>

      {error ? (
        <div className="mt-5">
          <ErrorNote message={error} onRetry={reload} />
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-ink-2">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Loading
        </div>
      ) : ops ? (
        <>
          <div className="mt-6 grid grid-cols-5 gap-3">
            <Stat label="Claims" value={int(ops.claims)} delay={0} />
            <Stat
              label="Straight-through rate"
              value={percent(ops.straight_through_rate)}
              hint={ops.straight_through_rate === null ? "No approved claims yet" : "Approved without corrections"}
              delay={40}
            />
            <Stat label="Latency p50" value={seconds(ops.latency_p50_s)} hint="Pipeline time per claim" delay={80} />
            <Stat label="Latency p95" value={seconds(ops.latency_p95_s)} hint="Pipeline time per claim" delay={120} />
            <Stat label="Tokens per claim" value={int(ops.tokens_per_claim)} hint="Input and output" delay={160} />
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <Card title="Claims per queue">
              <Bars rows={queueRows(ops)} total={ops.claims} />
            </Card>
            <Card title="Claims per status">
              {Object.keys(ops.by_status).length === 0 ? (
                <p className="text-sm text-ink-3">No claims yet.</p>
              ) : (
                <Bars rows={statusRows(ops)} total={ops.claims} />
              )}
            </Card>
          </div>

          <Card title={`Dead letter (${ops.dead_letter.length})`} className="mt-3">
            {ops.dead_letter.length === 0 ? (
              <EmptyState icon={CircleCheck} compact title="No failed claims." />
            ) : (
              <ul className="-mx-5 divide-y divide-line border-t border-line">
                {ops.dead_letter.map((d) => (
                  <li key={d.id} className="flex items-start gap-4 px-5 py-3">
                    <Link
                      href={`/claims/${d.id}`}
                      className="shrink-0 font-mono text-[13px] font-medium underline-offset-2 hover:underline"
                    >
                      {d.reference}
                    </Link>
                    <Chip variant="danger">Failed</Chip>
                    {d.error ? (
                      <details className="min-w-0 flex-1 text-xs text-red-800">
                        <summary className="cursor-pointer truncate font-mono">{firstLine(d.error, 160)}</summary>
                        <pre className="pane-scroll mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-red-50 p-2.5 font-mono text-[11px]">
                          {d.error}
                        </pre>
                      </details>
                    ) : (
                      <span className="text-xs text-ink-3">No error recorded</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
