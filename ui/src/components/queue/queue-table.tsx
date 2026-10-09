"use client";

import {
  ArrowDown,
  ArrowUp,
  CircleDot,
  Clock,
  Euro,
  Hash,
  Package,
  Tag,
  TriangleAlert,
  User,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Chip } from "@/components/ui/chip";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { CLAIM_TYPE, categoryEntry, statusEntry } from "@/lib/enums";
import { age, eur, firstLine, humanize, initials } from "@/lib/format";
import type { ClaimRow } from "@/lib/types";

type SortKey = "reference" | "insured" | "claimed" | "payout" | "age";

const SORTERS: Record<SortKey, (a: ClaimRow, b: ClaimRow) => number> = {
  reference: (a, b) => a.reference.localeCompare(b.reference),
  insured: (a, b) => (a.insured ?? "").localeCompare(b.insured ?? "", "sk"),
  claimed: (a, b) => Number(a.claimed_total_eur ?? -1) - Number(b.claimed_total_eur ?? -1),
  payout: (a, b) => Number(a.payout_eur ?? -1) - Number(b.payout_eur ?? -1),
  age: (a, b) => a.age_hours - b.age_hours,
};

function Th({
  icon: Icon,
  label,
  align = "left",
  sort,
  current,
  onSort,
  className,
}: {
  icon: LucideIcon;
  label: string;
  align?: "left" | "right";
  sort?: SortKey;
  current?: { key: SortKey; desc: boolean };
  onSort?: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort && current?.key === sort;
  const content = (
    <span className={cn("inline-flex items-center gap-1.5", align === "right" && "flex-row-reverse")}>
      <Icon className="size-3.5 text-ink-3" aria-hidden />
      {label}
      {active ? (
        current.desc ? (
          <ArrowDown className="size-3 text-ink" aria-hidden />
        ) : (
          <ArrowUp className="size-3 text-ink" aria-hidden />
        )
      ) : null}
    </span>
  );
  return (
    <th
      scope="col"
      aria-sort={active ? (current.desc ? "descending" : "ascending") : undefined}
      className={cn(
        "whitespace-nowrap px-3 py-2.5 text-[12px] font-medium text-ink-2 first:pl-5 last:pr-5",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {sort && onSort ? (
        <button type="button" onClick={() => onSort(sort)} className="rounded hover:text-ink">
          {content}
        </button>
      ) : (
        content
      )}
    </th>
  );
}

export function QueueTable({ rows, failed }: { rows: ClaimRow[]; failed: boolean }) {
  const router = useRouter();
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "age", desc: true });

  const sorted = useMemo(() => {
    const out = [...rows].sort(SORTERS[sort.key]);
    return sort.desc ? out.reverse() : out;
  }, [rows, sort]);

  function onSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "reference" && key !== "insured" }));
  }

  function open(id: string) {
    router.push(`/claims/${id}`);
  }

  const common = { current: sort, onSort };

  return (
    <div className="pane-scroll overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="border-b border-line bg-stone-50/70">
          <tr>
            <Th icon={Hash} label="Reference" sort="reference" {...common} />
            <Th icon={User} label="Insured" sort="insured" {...common} />
            {failed ? null : <Th icon={Tag} label="Claim type" />}
            {failed ? null : <Th icon={Package} label="Product" />}
            <Th icon={CircleDot} label="Status" />
            {failed ? (
              <Th icon={TriangleAlert} label="Error" className="w-full" />
            ) : (
              <>
                <Th icon={Euro} label="Claimed" align="right" sort="claimed" {...common} />
                <Th icon={Euro} label="Payout" align="right" sort="payout" {...common} />
                <Th icon={Zap} label="Straight-through" />
              </>
            )}
            <Th icon={Clock} label="Age" align="right" sort="age" {...common} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const status = statusEntry(r.status);
            const type = categoryEntry(CLAIM_TYPE, r.claim_type);
            return (
              <tr
                key={r.id}
                tabIndex={0}
                onClick={() => open(r.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") open(r.id);
                }}
                style={{ animationDelay: `${Math.min(i, 12) * 25}ms` }}
                className={cn(
                  "group animate-rise cursor-pointer border-b [&>td:first-child]:pl-5 [&>td:last-child]:pr-5 border-line/70 transition-colors last:border-b-0 hover:bg-marker-soft/60 focus-visible:bg-marker-soft/60 focus-visible:outline-none",
                  ["APPROVED", "SUBMITTED", "REJECTED"].includes(r.status) && "opacity-60",
                )}
              >
                <td className="whitespace-nowrap px-3 py-3 font-mono text-[13px] font-medium">{r.reference}</td>
                <td className="whitespace-nowrap px-3 py-3">
                  {r.insured ? (
                    <span className="flex items-center gap-2">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-stone-200 text-[10px] font-semibold text-ink-2">
                        {initials(r.insured)}
                      </span>
                      {r.insured}
                    </span>
                  ) : (
                    <span className="text-ink-3">Unknown</span>
                  )}
                </td>
                {failed ? null : (
                  <td className="whitespace-nowrap px-3 py-3">
                    {type ? (
                      <Chip dot variant={type.variant}>
                        {type.label}
                      </Chip>
                    ) : (
                      <span className="text-ink-3">–</span>
                    )}
                  </td>
                )}
                {failed ? null : (
                  <td className="whitespace-nowrap px-3 py-3 text-ink-2">{r.product ? humanize(r.product) : "–"}</td>
                )}
                <td className="whitespace-nowrap px-3 py-3">
                  <Chip variant={status.variant} icon={status.icon}>
                    {status.label}
                  </Chip>
                </td>
                {failed ? (
                  <td className="max-w-0 px-3 py-3">
                    <Tooltip content={r.error ? firstLine(r.error, 600) : null} className="w-full">
                      <span className="block truncate font-mono text-[12px] text-red-700">
                        {r.error ? firstLine(r.error) : "No error recorded"}
                      </span>
                    </Tooltip>
                  </td>
                ) : (
                  <>
                    <td className="tnum whitespace-nowrap px-3 py-3 text-right">{eur(r.claimed_total_eur)}</td>
                    <td className="tnum whitespace-nowrap px-3 py-3 text-right font-medium">{eur(r.payout_eur)}</td>
                    <td className="whitespace-nowrap px-3 py-3">
                      {r.straight_through ? (
                        <Tooltip content="Approved without field corrections">
                          <Chip variant="success" icon={Zap}>
                            Yes
                          </Chip>
                        </Tooltip>
                      ) : null}
                    </td>
                  </>
                )}
                <td className="tnum whitespace-nowrap px-3 py-3 text-right text-ink-2">{age(r.age_hours)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
