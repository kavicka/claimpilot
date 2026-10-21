"use client";

import { Avatar, DataTable, Tag, Tooltip, type Column } from "@crm-ui/react";
import { useRouter } from "next/navigation";

import { CLAIM_TYPE, DECIDED_STATUSES, categoryEntry, statusEntry } from "@/lib/enums";
import { age, eur, firstLine, humanize, initials } from "@/lib/format";
import type { ClaimRow } from "@/lib/types";

const money = (v: string | null) => (v === null ? -1 : Number(v));

const reference: Column<ClaimRow> = {
  key: "reference",
  header: "Reference",
  icon: "hash",
  width: 144,
  sortable: true,
  value: (r) => r.reference,
};

const insured: Column<ClaimRow> = {
  key: "insured",
  header: "Insured",
  icon: "user",
  sortable: true,
  value: (r) => r.insured,
  sortValue: (r) => r.insured ?? "",
  render: (r) =>
    r.insured ? (
      <span className="cp-td__person">
        <Avatar initials={initials(r.insured)} alt="" size={22} />
        <span className="cp-td__text">{r.insured}</span>
      </span>
    ) : (
      <span className="text-ink-subtle">Unknown</span>
    ),
};

const status: Column<ClaimRow> = {
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
};

const ageCol: Column<ClaimRow> = {
  key: "age",
  header: "Age",
  kind: "number",
  width: 96,
  sortable: true,
  value: (r) => age(r.age_hours),
  sortValue: (r) => r.age_hours,
};

const COLUMNS: Column<ClaimRow>[] = [
  reference,
  insured,
  {
    key: "type",
    header: "Claim type",
    icon: "tag",
    width: 116,
    value: (r) => r.claim_type,
    render: (r) => {
      const t = categoryEntry(CLAIM_TYPE, r.claim_type);
      return t ? (
        <Tag tone={t.tone} dot size="md">
          {t.label}
        </Tag>
      ) : (
        <span className="text-ink-subtle">–</span>
      );
    },
  },
  {
    key: "product",
    header: "Product",
    icon: "package",
    width: 88,
    value: (r) => (r.product ? humanize(r.product) : "–"),
  },
  status,
  {
    key: "claimed",
    header: "Claimed",
    kind: "number",
    width: 112,
    sortable: true,
    value: (r) => eur(r.claimed_total_eur),
    sortValue: (r) => money(r.claimed_total_eur),
  },
  {
    key: "payout",
    header: "Payout",
    kind: "number",
    width: 112,
    sortable: true,
    value: (r) => eur(r.payout_eur),
    sortValue: (r) => money(r.payout_eur),
  },
  {
    key: "straight",
    header: "Straight-through",
    icon: "zap",
    width: 140,
    value: (r) => (r.straight_through ? "Yes" : ""),
    render: (r) =>
      r.straight_through ? (
        <Tooltip content="Approved without field corrections">
          <Tag tone="success" icon="zap" size="md">
            Yes
          </Tag>
        </Tooltip>
      ) : null,
  },
  ageCol,
];

const FAILED_COLUMNS: Column<ClaimRow>[] = [
  reference,
  { ...insured, width: 200 },
  status,
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
  ageCol,
];

export function QueueTable({
  rows,
  failed,
  empty,
  isNew,
}: {
  rows: ClaimRow[];
  failed: boolean;
  empty: React.ReactNode;
  isNew?: (row: ClaimRow) => boolean;
}) {
  const router = useRouter();
  return (
    <DataTable
      label="Claims"
      columns={failed ? FAILED_COLUMNS : COLUMNS}
      rows={rows}
      rowKey={(r) => r.id}
      onRowClick={(r) => router.push(`/claims/${r.id}`)}
      isInactive={(r) => DECIDED_STATUSES.includes(r.status)}
      isNew={isNew}
      defaultSort={{ key: "age", dir: "desc" }}
      empty={empty}
    />
  );
}
