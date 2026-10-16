"use client";

import {
  Alert,
  Button,
  Checkbox,
  DataTable,
  EmptyState,
  IconButton,
  SearchField,
  Spinner,
  TableToolbar,
  Tabs,
  Tag,
  Tooltip,
  useToast,
  type Column,
  type TabItem,
} from "@claimpilot/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { DataPage } from "@/components/shell/page";
import { problemOf } from "@/components/upload/upload-view";
import { api, errorMessage } from "@/lib/api";
import { INVOICE_DECIDED_STATUSES, INVOICE_KIND, INVOICE_PIPELINE_STATUSES, INVOICE_RULE, QUEUE, categoryEntry, statusEntry } from "@/lib/enums";
import { age, firstLine, money } from "@/lib/format";
import type { InvoiceRow } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

type TabKey = "fast_track" | "standard" | "senior" | "fraud_review" | "pipeline" | "needs_info" | "failed";

const TAB_LABEL: Record<TabKey, string> = {
  fast_track: "Fast track",
  standard: "Standard",
  senior: "Senior",
  fraud_review: "Fraud review",
  pipeline: "In pipeline",
  needs_info: "Needs info",
  failed: "Failed",
};

const ORDER: TabKey[] = ["fast_track", "standard", "senior", "fraud_review", "pipeline", "needs_info", "failed"];
const QUEUE_TABS = new Set<TabKey>(["fast_track", "standard", "senior", "fraud_review"]);

const EMPTY: Record<TabKey, string> = {
  fast_track: "No invoices waiting in the fast-track queue.",
  standard: "No invoices waiting in the standard queue.",
  senior: "No invoices waiting in the senior queue.",
  fraud_review: "No invoices waiting in fraud review.",
  pipeline: "No invoices are being processed.",
  needs_info: "No invoices are waiting for the supplier.",
  failed: "No failed invoices.",
};

function inTab(row: InvoiceRow, tab: TabKey, withDecided: boolean): boolean {
  if (tab === "pipeline") return INVOICE_PIPELINE_STATUSES.includes(row.status);
  if (tab === "needs_info") return row.status === "NEEDS_INFO";
  if (tab === "failed") return row.status === "FAILED";
  if (row.queue !== tab) return false;
  return row.status === "IN_REVIEW" || (withDecided && INVOICE_DECIDED_STATUSES.includes(row.status));
}

function isTab(v: string | null): v is TabKey {
  return v !== null && (ORDER as string[]).includes(v);
}

const amount = (v: string | null) => (v === null ? Number.NEGATIVE_INFINITY : Number(v));

const COLUMNS: Column<InvoiceRow>[] = [
  { key: "reference", header: "Reference", icon: "hash", width: 140, sortable: true, value: (r) => r.reference },
  {
    key: "supplier",
    header: "Supplier",
    icon: "building-02",
    sortable: true,
    value: (r) => r.supplier,
    sortValue: (r) => r.supplier ?? "",
    render: (r) => (r.supplier ? <span className="cp-td__text">{r.supplier}</span> : <span className="text-ink-subtle">Not read</span>),
  },
  { key: "number", header: "Number", width: 120, value: (r) => r.invoice_number ?? "–" },
  {
    key: "kind",
    header: "Kind",
    icon: "tag",
    width: 112,
    value: (r) => r.kind,
    render: (r) => {
      const k = categoryEntry(INVOICE_KIND, r.kind);
      return k ? (
        <Tag tone={k.tone} dot size="md">
          {k.label}
        </Tag>
      ) : (
        <span className="text-ink-subtle">–</span>
      );
    },
  },
  {
    key: "total",
    header: "Total",
    kind: "number",
    width: 120,
    sortable: true,
    value: (r) => (r.total === null ? "–" : money(r.total, r.currency ?? "EUR")),
    sortValue: (r) => amount(r.total),
  },
  {
    key: "queue",
    header: "Queue",
    icon: "inbox",
    width: 120,
    value: (r) => r.queue,
    render: (r) => {
      const q = categoryEntry(QUEUE, r.queue);
      return q ? (
        <Tag tone={q.tone} dot size="md">
          {q.label}
        </Tag>
      ) : (
        <span className="text-ink-subtle">–</span>
      );
    },
  },
  {
    key: "status",
    header: "Status",
    icon: "circle-dashed",
    width: 116,
    value: (r) => statusEntry(r.status).label,
    render: (r) => {
      const s = statusEntry(r.status);
      return (
        <Tag tone={s.tone} icon={s.icon ?? null} size="md">
          {s.label}
        </Tag>
      );
    },
  },
  {
    key: "findings",
    header: "Findings",
    kind: "number",
    width: 96,
    sortable: true,
    value: (r) => r.findings,
    render: (r) => (r.findings ? <span className="text-danger-ink">{r.findings}</span> : <span className="text-ink-subtle">0</span>),
  },
  {
    key: "rule",
    header: "Rule",
    width: 72,
    value: (r) => r.rule,
    render: (r) =>
      r.rule ? (
        <Tooltip content={INVOICE_RULE[r.rule] ?? r.rule}>
          <Tag tone="neutral" size="md">
            {r.rule}
          </Tag>
        </Tooltip>
      ) : null,
  },
  {
    key: "age",
    header: "Age",
    kind: "number",
    width: 88,
    sortable: true,
    value: (r) => age(r.age_hours),
    sortValue: (r) => r.age_hours,
  },
];

const FAILED_COLUMNS: Column<InvoiceRow>[] = [
  COLUMNS[0]!,
  { ...COLUMNS[1]!, width: 200 },
  COLUMNS[6]!,
  {
    key: "error",
    header: "Error",
    icon: "warning",
    value: (r) => r.error,
    render: (r) => (
      <Tooltip content={r.error ? firstLine(r.error, 600) : null} className="w-full">
        <span className="cp-td__text text-danger-ink">{r.error ? firstLine(r.error) : "No error recorded"}</span>
      </Tooltip>
    ),
  },
  COLUMNS[9]!,
];

export function InvoiceQueue() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const notify = useToast();
  const { data, error, loading, reload } = useFetch("invoices", () => api.invoices(), { pollMs: 15000 });
  const [search, setSearch] = useState("");
  const [withDecided, setWithDecided] = useState(false);
  const [sending, setSending] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const rows = useMemo(() => data ?? [], [data]);
  const counts = useMemo(() => {
    const c = Object.fromEntries(ORDER.map((t) => [t, 0])) as Record<TabKey, number>;
    for (const r of rows) for (const t of ORDER) if (inTab(r, t, false)) c[t] += 1;
    return c;
  }, [rows]);

  const requested = params.get("tab");
  const tab: TabKey = isTab(requested) ? requested : (ORDER.find((t) => counts[t] > 0) ?? "standard");

  function selectTab(next: TabKey) {
    const q = new URLSearchParams(params.toString());
    q.set("tab", next);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    const problem = problemOf(file);
    if (problem) {
      setUploadError(`Not uploaded: ${problem}.`);
      return;
    }
    setSending(true);
    setUploadError(null);
    try {
      const created = await api.uploadInvoice(file);
      notify("success", `${created.reference} created`, `${file.name} sent to the pipeline.`);
      reload();
      selectTab("pipeline");
    } catch (err) {
      setUploadError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  const needle = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      rows
        .filter((r) => inTab(r, tab, withDecided))
        .filter(
          (r) =>
            !needle ||
            r.reference.toLowerCase().includes(needle) ||
            (r.supplier ?? "").toLowerCase().includes(needle) ||
            (r.invoice_number ?? "").toLowerCase().includes(needle),
        ),
    [rows, tab, withDecided, needle],
  );

  const tabs: TabItem<TabKey>[] = ORDER.map((key) => ({
    key,
    label: TAB_LABEL[key],
    count: counts[key],
    flag: key === "failed" && counts.failed > 0 ? "danger" : undefined,
  }));

  const inReview = counts.fast_track + counts.standard + counts.senior + counts.fraud_review;

  const empty = loading ? (
    <div className="flex items-center justify-center gap-8 py-80 text-ink-subtle" role="status">
      <Spinner /> Loading invoices
    </div>
  ) : (
    <EmptyState
      icon={needle ? "search-remove" : tab === "failed" ? "alert-circle" : "inbox"}
      title={needle ? `No invoices match “${search.trim()}”.` : EMPTY[tab]}
      description={
        !needle && QUEUE_TABS.has(tab) && counts.pipeline > 0
          ? `${counts.pipeline} ${counts.pipeline === 1 ? "invoice is" : "invoices are"} still in the pipeline.`
          : undefined
      }
    />
  );

  return (
    <DataPage
      crumbs={[{ label: "Invoices", href: "/invoices" }, { label: "Queue" }]}
      meta="Refreshes every 15 seconds"
      actions={
        <Tooltip content="Reload now" side="bottom">
          <IconButton variant="toolbar" icon="refresh" iconSize={16} label="Reload" onClick={reload} />
        </Tooltip>
      }
      title="Invoices"
      subtitle={
        data ? (
          <>
            <span className="tnum">{inReview}</span> in review · <span className="tnum">{counts.pipeline}</span> in the
            pipeline · <span className="tnum">{rows.length}</span> total
          </>
        ) : (
          " "
        )
      }
    >
      <TableToolbar
        actions={
          <>
            {QUEUE_TABS.has(tab) ? (
              <Checkbox variant="table" checked={withDecided} onCheckedChange={setWithDecided}>
                Show decided
              </Checkbox>
            ) : null}
            <div className="w-[220px]">
              <SearchField
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Reference, supplier or number"
                aria-label="Search invoices"
              />
            </div>
            <Tooltip content="One PDF, JPG or PNG per invoice, up to 20 MB" side="bottom">
              <Button variant="primary" icon="plus" loading={sending} onClick={() => input.current?.click()}>
                Upload invoice
              </Button>
            </Tooltip>
            <input
              ref={input}
              type="file"
              hidden
              aria-label="Invoice file"
              accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
              onChange={(e) => {
                upload(e.target.files?.[0]);
                e.target.value = ""; // choosing the same file again fires change again
              }}
            />
          </>
        }
      >
        <Tabs tabs={tabs} value={tab} onValueChange={selectTab} label="Invoice queues" />
      </TableToolbar>

      {uploadError ? (
        <Alert tone="danger" action={{ label: "Dismiss", onClick: () => setUploadError(null) }}>
          {uploadError}
        </Alert>
      ) : null}
      {error ? (
        <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
          {error}
        </Alert>
      ) : null}

      <DataTable
        label="Invoices"
        columns={tab === "failed" ? FAILED_COLUMNS : COLUMNS}
        rows={loading ? [] : visible}
        rowKey={(r) => r.id}
        onRowClick={(r) => router.push(`/invoices/${r.id}`)}
        isInactive={(r) => INVOICE_DECIDED_STATUSES.includes(r.status)}
        defaultSort={{ key: "age", dir: "desc" }}
        empty={empty}
      />

      <p className="cp-text-meta text-ink-subtle" hidden={!data}>
        Findings count failed validation checks and differences from the ERP order. Approved, exported and rejected invoices
        appear with Show decided.
      </p>
    </DataPage>
  );
}
