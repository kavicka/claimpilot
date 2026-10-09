"use client";

import { FlaskConical, LoaderCircle } from "lucide-react";

import { EmptyState, ErrorNote } from "@/components/ui/empty-state";
import { api } from "@/lib/api";
import { humanize, int, metric, when } from "@/lib/format";
import type { EvalReport } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function opsLine(ops: Record<string, unknown>): string[] {
  const out: string[] = [];
  const calls = num(ops.llm_calls);
  const cached = num(ops.cached_calls);
  const perItem = num(ops.tokens_per_item);
  const p50 = num(ops.latency_p50_ms);
  const p95 = num(ops.latency_p95_ms);
  const rss = num(ops.worker_peak_rss_mb);
  if (calls !== null) out.push(`${int(calls)} LLM calls${cached ? ` (${int(cached)} cached)` : ""}`);
  if (perItem) out.push(`${int(perItem)} tokens per item`);
  if (p50) out.push(`p50 ${(p50 / 1000).toFixed(1)} s`);
  if (p95) out.push(`p95 ${(p95 / 1000).toFixed(1)} s`);
  if (rss) out.push(`worker peak ${int(rss)} MB`);
  return out;
}

function SuiteCard({ report, index }: { report: EvalReport; index: number }) {
  const metrics = Object.entries(report.metrics);
  const models = report.models ?? [];
  const ops = opsLine(report.ops ?? {});
  return (
    <article
      className="animate-rise flex flex-col rounded-2xl border border-line bg-sheet shadow-[0_1px_2px_rgb(0_0_0/0.03)]"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-5 py-3.5">
        <h2 className="font-mono text-[15px] font-medium">{report.suite}</h2>
        <span className="tnum text-xs text-ink-3">{when(report.created)}</span>
      </header>

      <div className="px-5 py-3">
        {metrics.length === 0 ? (
          <p className="text-sm text-ink-3">No metrics in this report.</p>
        ) : (
          <table className="w-full text-[13px]">
            <tbody>
              {metrics.map(([name, m]) => (
                <tr key={name} className="border-b border-line/70 last:border-b-0">
                  <td className="py-1.5 pr-3 text-ink-2">{humanize(name)}</td>
                  <td className="tnum py-1.5 text-right font-medium">{metric(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-auto flex flex-col gap-2.5 border-t border-line bg-stone-50/50 px-5 py-3 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-ink-3">Models</span>
          {models.length ? (
            models.map((m) => (
              <span key={m} className="rounded bg-white px-1.5 py-px font-mono text-[11px] text-ink-2 ring-1 ring-line">
                {m}
              </span>
            ))
          ) : (
            <span className="text-ink-2">none (no model calls)</span>
          )}
        </div>
        {ops.length ? <p className="tnum text-ink-2">{ops.join(" · ")}</p> : null}
        {report.notes.length ? (
          <ul className="flex flex-col gap-1 text-ink-2">
            {report.notes.map((n, i) => (
              <li key={i} className="flex gap-2">
                <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-3" />
                <span>{n}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </article>
  );
}

export function EvalsView() {
  const { data, error, loading, reload } = useFetch("evals", api.evals);

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-7">
      <header>
        <h1 className="text-[22px] font-semibold tracking-tight">Evals</h1>
        <p className="mt-0.5 text-sm text-ink-2">Latest dev-split report per suite.</p>
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
      ) : data && data.length === 0 ? (
        <div className="mt-6 rounded-2xl border border-line bg-sheet">
          <EmptyState
            icon={FlaskConical}
            title="No eval reports."
            description={
              <>
                The API reads <code className="font-mono text-[12.5px]">evals/reports/*-dev.json</code> and found none.
              </>
            }
          />
        </div>
      ) : data ? (
        <div className="mt-6 grid grid-cols-2 gap-3">
          {data.map((r, i) => (
            <SuiteCard key={r.suite} report={r} index={i} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
