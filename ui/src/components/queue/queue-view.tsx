"use client";

import { Alert, Checkbox, EmptyState, IconButton, SearchField, Spinner, TableToolbar, Tabs, Tooltip, type TabItem } from "@claimpilot/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { DataPage } from "@/components/shell/page";
import { api } from "@/lib/api";
import { DECIDED_STATUSES, PIPELINE_STATUSES } from "@/lib/enums";
import type { ClaimRow } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

import { QueueTable } from "./queue-table";

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
  fast_track: "No claims waiting in the fast-track queue.",
  standard: "No claims waiting in the standard queue.",
  senior: "No claims waiting in the senior queue.",
  fraud_review: "No claims waiting in fraud review.",
  pipeline: "No claims are being processed.",
  needs_info: "No claims are waiting for information from the client.",
  failed: "No failed claims.",
};

function inTab(row: ClaimRow, tab: TabKey, withDecided: boolean): boolean {
  if (tab === "pipeline") return PIPELINE_STATUSES.includes(row.status);
  if (tab === "needs_info") return row.status === "NEEDS_INFO";
  if (tab === "failed") return row.status === "FAILED";
  if (row.queue !== tab) return false;
  return row.status === "IN_REVIEW" || (withDecided && DECIDED_STATUSES.includes(row.status));
}

function isTab(v: string | null): v is TabKey {
  return v !== null && (ORDER as string[]).includes(v);
}

export function QueueView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { data, error, loading, reload } = useFetch("claims", () => api.claims(), { pollMs: 15000 });
  const [search, setSearch] = useState("");
  const [withDecided, setWithDecided] = useState(false);

  const rows = useMemo(() => data ?? [], [data]);
  const counts = useMemo(() => {
    const c = Object.fromEntries(ORDER.map((t) => [t, 0])) as Record<TabKey, number>;
    for (const r of rows) for (const t of ORDER) if (inTab(r, t, false)) c[t] += 1;
    return c;
  }, [rows]);

  const requested = params.get("tab");
  const tab: TabKey = isTab(requested) ? requested : (ORDER.find((t) => counts[t] > 0) ?? "fast_track");

  function selectTab(next: TabKey) {
    const q = new URLSearchParams(params.toString());
    q.set("tab", next);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  const needle = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      rows
        .filter((r) => inTab(r, tab, withDecided))
        .filter((r) => !needle || r.reference.toLowerCase().includes(needle) || (r.insured ?? "").toLowerCase().includes(needle)),
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
      <Spinner /> Loading claims
    </div>
  ) : (
    <EmptyState
      icon={needle ? "search-remove" : tab === "failed" ? "alert-circle" : "inbox"}
      title={needle ? `No claims match “${search.trim()}”.` : EMPTY[tab]}
      description={
        !needle && QUEUE_TABS.has(tab) && counts.pipeline > 0
          ? `${counts.pipeline} ${counts.pipeline === 1 ? "claim is" : "claims are"} still in the pipeline.`
          : undefined
      }
    />
  );

  return (
    <DataPage
      crumbs={[{ label: "Claims", href: "/" }, { label: "Queue" }]}
      meta="Refreshes every 15 seconds"
      actions={
        <Tooltip content="Reload now" side="bottom">
          <IconButton variant="toolbar" icon="refresh" iconSize={16} label="Reload" onClick={reload} />
        </Tooltip>
      }
      title="Queue"
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
                placeholder="Reference or name"
                aria-label="Search claims"
              />
            </div>
          </>
        }
      >
        <Tabs tabs={tabs} value={tab} onValueChange={selectTab} label="Queues" />
      </TableToolbar>

      {error ? (
        <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
          {error}
        </Alert>
      ) : null}

      <QueueTable rows={loading ? [] : visible} failed={tab === "failed"} empty={empty} />

      <p className="cp-text-meta text-ink-subtle" hidden={!data}>
        Queue tabs list claims in review. Approved, submitted and rejected claims appear with Show decided.
      </p>
    </DataPage>
  );
}
