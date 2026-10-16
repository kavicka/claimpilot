"use client";

import { Alert, EmptyState, Spinner, Tag } from "@claimpilot/ui";

import { DataPage } from "@/components/shell/page";
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
      className="flex animate-rise flex-col overflow-hidden rounded-(--radius-12) bg-surface hairline"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <header className="flex items-baseline justify-between gap-12 px-16 py-12 hairline-b">
        <h2 className="cp-text-panel-title text-ink">{report.suite}</h2>
        <span className="cp-text-meta tnum text-ink-subtle">{when(report.created)}</span>
      </header>

      <div className="px-16 py-8">
        {metrics.length === 0 ? (
          <p className="cp-text-cell text-ink-subtle">No metrics in this report.</p>
        ) : (
          <table className="cp-text-cell w-full text-ink-cell">
            <tbody>
              {metrics.map(([name, m]) => (
                <tr key={name} className="hairline-b last:shadow-none">
                  <td className="py-8 pr-12 text-ink-subtle">{humanize(name)}</td>
                  <td className="cp-text-tab tnum py-8 text-right">{metric(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="cp-text-label-regular mt-auto flex flex-col gap-8 bg-surface-popover-footer px-16 py-10 text-ink-subtle hairline-t">
        <div className="flex flex-wrap items-center gap-6">
          <span>Models</span>
          {models.length ? models.map((m) => <Tag key={m} tone="neutral">{m}</Tag>) : <span>none (no model calls)</span>}
        </div>
        {ops.length ? <p className="tnum">{ops.join(" · ")}</p> : null}
        {report.notes.length ? (
          <ul className="flex list-disc flex-col gap-4 pl-16">
            {report.notes.map((n, i) => (
              <li key={i}>{n}</li>
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
    <DataPage crumbs={[{ label: "Operations", href: "/ops" }, { label: "Evals" }]} title="Evals" subtitle="Latest dev-split report per suite.">
      {error ? (
        <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-8 py-96 text-ink-subtle" role="status">
          <Spinner /> Loading
        </div>
      ) : data && data.length === 0 ? (
        <div className="rounded-(--radius-12) hairline">
          <EmptyState
            icon="flask"
            title="No eval reports."
            description={<>The API reads evals/reports/*-dev.json and found none.</>}
          />
        </div>
      ) : data ? (
        <div className="grid grid-cols-2 gap-12">
          {data.map((r, i) => (
            <SuiteCard key={r.suite} report={r} index={i} />
          ))}
        </div>
      ) : null}
    </DataPage>
  );
}
