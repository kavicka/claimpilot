"use client";

import { Avatar, Board, BoardCard, BoardColumn, Tag } from "@crm-ui/react";
import { useRouter } from "next/navigation";

import { CLAIM_TYPE, QUEUES, categoryEntry, queueEntry } from "@/lib/enums";
import { age, eur, initials } from "@/lib/format";
import type { ClaimRow, QueueName } from "@/lib/types";

const TONE: Record<QueueName, "success" | "info" | "purple" | "danger"> = {
  fast_track: "success",
  standard: "info",
  senior: "purple",
  fraud_review: "danger",
};

/**
 * Claims in review as a board, one column per queue, oldest first. Read-only: a claim changes queue by
 * a handler's decision (escalate), not by dragging.
 */
export function QueueBoard({ rows, isNew }: { rows: ClaimRow[]; isNew: (r: ClaimRow) => boolean }) {
  const router = useRouter();
  return (
    <Board label="Claims in review by queue">
      {QUEUES.map((q) => {
        const items = rows.filter((r) => r.queue === q && r.status === "IN_REVIEW").sort((a, b) => b.age_hours - a.age_hours);
        const total = items.reduce((n, r) => n + Number(r.claimed_total_eur ?? 0), 0);
        const entry = queueEntry(q)!;
        return (
          <BoardColumn
            key={q}
            columnKey={q}
            title={entry.label}
            icon={q === "fraud_review" ? "shield-alert" : "circle"}
            tone={TONE[q]}
            count={items.length}
            total={items.length ? eur(total) : undefined}
            empty={`No claims waiting in ${entry.label.toLowerCase()}.`}
          >
            {items.map((r) => {
              const type = categoryEntry(CLAIM_TYPE, r.claim_type);
              return (
                <div key={r.id} data-flash={isNew(r) ? "a" : undefined} className="rounded-(--radius-10)">
                  <BoardCard
                    id={r.id}
                    label={`${r.reference}, ${r.insured ?? "unknown insured"}`}
                    title={r.reference}
                    media={<Avatar initials={r.insured ? initials(r.insured) : "?"} alt="" size={28} />}
                    meta={`${r.insured ?? "Unknown"} · ${eur(r.claimed_total_eur)}`}
                    description={`${age(r.age_hours)} in the queue`}
                    tags={
                      type ? (
                        <Tag tone={type.tone} dot>
                          {type.label}
                        </Tag>
                      ) : undefined
                    }
                    onOpen={() => router.push(`/claims/${r.id}`)}
                  />
                </div>
              );
            })}
          </BoardColumn>
        );
      })}
    </Board>
  );
}
