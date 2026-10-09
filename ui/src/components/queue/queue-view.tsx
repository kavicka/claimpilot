"use client";

import { CircleAlert, Inbox, LoaderCircle, RefreshCw, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { EmptyState, ErrorNote } from "@/components/ui/empty-state";
import { PillTabs, type TabItem } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
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

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows
      .filter((r) => inTab(r, tab, withDecided))
      .filter(
        (r) =>
          !needle ||
          r.reference.toLowerCase().includes(needle) ||
          (r.insured ?? "").toLowerCase().includes(needle),
      );
  }, [rows, tab, withDecided, search]);

  const tabs: TabItem<TabKey>[] = ORDER.map((key) => ({
    key,
    label: TAB_LABEL[key],
    count: counts[key],
    flag: key === "failed" && counts.failed > 0 ? "danger" : undefined,
  }));

  const inReview = counts.fast_track + counts.standard + counts.senior + counts.fraud_review;

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-7">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Queue</h1>
          <p className="mt-0.5 text-sm text-ink-2">
            {data ? (
              <>
                <span className="tnum">{inReview}</span> in review · <span className="tnum">{counts.pipeline}</span> in
                the pipeline · <span className="tnum">{rows.length}</span> total
              </>
            ) : (
              " "
            )}
          </p>
        </div>
        <Tooltip content="Reload now. The list also refreshes every 15 seconds." side="bottom">
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

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <PillTabs tabs={tabs} value={tab} onChange={selectTab} label="Queues" className="shrink-0" />
        <div className="flex items-center gap-3">
          {QUEUE_TABS.has(tab) ? (
            <label className="flex cursor-pointer select-none items-center gap-2 text-[13px] text-ink-2">
              <input
                type="checkbox"
                checked={withDecided}
                onChange={(e) => setWithDecided(e.target.checked)}
                className="size-3.5 accent-ink"
              />
              Show decided
            </label>
          ) : null}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Reference or name"
              aria-label="Search claims"
              className="h-9 w-52 rounded-lg border border-line-2 bg-sheet pl-8 pr-8 text-sm outline-none transition placeholder:text-ink-3 focus:border-ink focus:ring-2 focus:ring-ink/10"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-3 hover:text-ink"
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {error ? (
        <div className="mt-4">
          <ErrorNote message={error} onRetry={reload} />
        </div>
      ) : null}

      <section className="mt-4 overflow-hidden rounded-2xl border border-line bg-sheet shadow-[0_1px_2px_rgb(0_0_0/0.03)]">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm text-ink-2">
            <LoaderCircle className="size-4 animate-spin" aria-hidden /> Loading claims
          </div>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={search ? Search : tab === "failed" ? CircleAlert : Inbox}
            title={search ? `No claims match “${search.trim()}”.` : EMPTY[tab]}
            description={
              !search && QUEUE_TABS.has(tab) && counts.pipeline > 0
                ? `${counts.pipeline} ${counts.pipeline === 1 ? "claim is" : "claims are"} still in the pipeline.`
                : undefined
            }
          />
        ) : (
          <QueueTable rows={visible} failed={tab === "failed"} />
        )}
      </section>
      <p className={cn("mt-3 text-xs text-ink-3", !data && "invisible")}>
        Queue tabs list claims in review. Approved, submitted and rejected claims appear with Show decided.
      </p>
    </div>
  );
}
