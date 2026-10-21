"use client";

import {
  Alert,
  BarChart,
  ChartCard,
  DataTable,
  Donut,
  EmptyState,
  IconButton,
  KpiCard,
  SegmentBar,
  Spinner,
  Tag,
  Tooltip,
  type BarDatum,
  type MetricTone,
  type Segment,
} from "@crm-ui/react";
import { useRouter } from "next/navigation";

import { DataPage } from "@/components/shell/page";
import { api } from "@/lib/api";
import { DECIDED_STATUSES, PIPELINE_STATUSES, QUEUES, STATUS_ORDER, queueEntry, statusEntry } from "@/lib/enums";
import { firstLine, int, percent, seconds } from "@/lib/format";
import type { Ops } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

/** One figure as a KPI card. No delta or trend: the api reports current totals only. */
function Stat({ label, value, hint, index }: { label: string; value: string; hint?: string; index: number }) {
  return (
    <div className="animate-rise" style={{ animationDelay: `${index * 40}ms` }}>
      <KpiCard title={label} value={value} comparison={hint ?? " "} className="h-full" />
    </div>
  );
}

const QUEUE_TONE: Record<string, MetricTone> = { fast_track: "success", standard: "accent", senior: "purple", fraud_review: "danger" };

/** Claims per queue as one bar that adds up to all routed claims. */
function queueSegments(ops: Ops): Segment[] {
  const keys = [...QUEUES, ...Object.keys(ops.by_queue).filter((k) => !(QUEUES as readonly string[]).includes(k))];
  return keys.map((k) => {
    const n = ops.by_queue[k] ?? 0;
    return { key: k, label: queueEntry(k)?.label ?? "Not routed", value: n, display: int(n), detail: n === 1 ? "claim" : "claims", tone: QUEUE_TONE[k] ?? "neutral" };
  });
}

/** Statuses folded into the phases a handler thinks in. */
function phaseSegments(ops: Ops): Segment[] {
  const sum = (match: (s: string) => boolean) => Object.entries(ops.by_status).reduce((n, [s, c]) => n + (match(s) ? c : 0), 0);
  return [
    { key: "pipeline", label: "In pipeline", value: sum((s) => (PIPELINE_STATUSES as string[]).includes(s)), tone: "soft" },
    { key: "review", label: "In review", value: sum((s) => s === "IN_REVIEW"), tone: "accent" },
    { key: "info", label: "Needs info", value: sum((s) => s === "NEEDS_INFO"), tone: "warning" },
    { key: "decided", label: "Decided", value: sum((s) => (DECIDED_STATUSES as string[]).includes(s)), tone: "success" },
    { key: "failed", label: "Failed", value: sum((s) => s === "FAILED"), tone: "danger" },
  ];
}

/** Tick values for a count axis: 0 and up to four steps of 1, 2 or 5 × 10^n. */
function countTicks(max: number): { ticks: number[]; top: number } {
  if (max <= 0) return { ticks: [0, 1], top: 1 };
  const raw = max / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const top = Math.ceil(max / step) * step;
  return { ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step), top };
}

function Bars({ data }: { data: BarDatum[] }) {
  const { ticks, top } = countTicks(Math.max(0, ...data.map((d) => d.value)));
  return (
    <BarChart
      data={data}
      max={top}
      ticks={ticks}
      size="md"
      labelWidth={96}
      formatTick={(v) => String(v)}
      formatValue={(v) => `${int(v)} ${v === 1 ? "claim" : "claims"}`}
      valueCaption=""
    />
  );
}


function statusRows(ops: Ops): BarDatum[] {
  const known = STATUS_ORDER.filter((s) => ops.by_status[s]);
  const extra = Object.keys(ops.by_status).filter((s) => !(STATUS_ORDER as string[]).includes(s));
  return [...known, ...extra].map((s, i) => ({ label: statusEntry(s).label, value: ops.by_status[s] ?? 0, color: ((i % 3) + 1) as 1 | 2 | 3 }));
}

type DeadLetter = Ops["dead_letter"][number];

export function OpsView() {
  const router = useRouter();
  const { data: ops, error, loading, reload } = useFetch("ops", api.ops, { pollMs: 30000 });

  return (
    <DataPage
      crumbs={[{ label: "Operations", href: "/ops" }, { label: "Ops" }]}
      meta="Refreshes every 30 seconds"
      actions={
        <Tooltip content="Reload now" side="bottom">
          <IconButton variant="toolbar" icon="refresh" iconSize={16} label="Reload" onClick={reload} />
        </Tooltip>
      }
      title="Ops"
      subtitle="Throughput, latency and failures across all claims."
    >
      {error ? (
        <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-8 py-96 text-ink-subtle" role="status">
          <Spinner /> Loading
        </div>
      ) : ops ? (
        <>
          <div className="grid grid-cols-5 gap-12">
            <Stat label="Claims" value={int(ops.claims)} index={0} />
            <Stat
              label="Straight-through rate"
              value={percent(ops.straight_through_rate)}
              hint={ops.straight_through_rate === null ? "No approved claims yet" : "Approved without corrections"}
              index={1}
            />
            <Stat label="Latency p50" value={seconds(ops.latency_p50_s)} hint="Pipeline time per claim" index={2} />
            <Stat label="Latency p95" value={seconds(ops.latency_p95_s)} hint="Pipeline time per claim" index={3} />
            <Stat label="Tokens per claim" value={int(ops.tokens_per_claim)} hint="Input and output" index={4} />
          </div>

          <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-12">
            <ChartCard title="Claims per queue" icon="route">
              <SegmentBar label="Claims per queue" segments={queueSegments(ops)} />
            </ChartCard>
            <ChartCard title="Claims by phase" icon="workflow">
              <Donut label="Claims by phase" center={{ value: int(ops.claims), label: ops.claims === 1 ? "claim" : "claims" }} segments={phaseSegments(ops)} />
            </ChartCard>
          </div>

          <div className="grid grid-cols-1 gap-12">
            <ChartCard title="Claims per status">
              {Object.keys(ops.by_status).length === 0 ? (
                <p className="cp-text-cell text-ink-subtle">No claims yet.</p>
              ) : (
                <Bars data={statusRows(ops)} />
              )}
            </ChartCard>
          </div>

          <h2 className="cp-text-panel-title mt-20 text-ink">Dead letter ({ops.dead_letter.length})</h2>
          <DataTable<DeadLetter>
            label="Dead letter"
            rows={ops.dead_letter}
            rowKey={(d) => d.id}
            onRowClick={(d) => router.push(`/claims/${d.id}`)}
            empty={<EmptyState icon="circle-check" title="No failed claims." />}
            columns={[
              { key: "reference", header: "Reference", icon: "hash", width: 170, value: (d) => d.reference },
              {
                key: "status",
                header: "Status",
                icon: "circle-dashed",
                width: 120,
                value: () => "Failed",
                render: () => (
                  <Tag tone="danger" icon="alert-circle" size="md">
                    Failed
                  </Tag>
                ),
              },
              {
                key: "error",
                header: "Error",
                icon: "warning",
                value: (d) => d.error,
                render: (d) => (
                  <Tooltip content={d.error ? firstLine(d.error, 600) : null} className="w-full">
                    <span className="cp-td__text text-danger-ink">{d.error ? firstLine(d.error, 160) : "No error recorded"}</span>
                  </Tooltip>
                ),
              },
            ]}
          />
        </>
      ) : null}
    </DataPage>
  );
}
