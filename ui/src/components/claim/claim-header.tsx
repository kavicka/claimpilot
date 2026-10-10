"use client";

import { ArrowLeft, ArrowUpRight, Ban, Check, CircleAlert, CircleHelp, LoaderCircle, Lock, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useUser } from "@/components/shell/auth";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Tooltip } from "@/components/ui/tooltip";
import { CLAIM_TYPE, categoryEntry, queueEntry, statusEntry } from "@/lib/enums";
import { eur, firstLine, humanize } from "@/lib/format";
import type { ClaimAction, ClaimDetail } from "@/lib/types";

import { ActionDialog } from "./action-dialog";

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px]">{children}</dd>
    </div>
  );
}

export function ClaimHeader({
  claim,
  error,
  running,
  onChanged,
}: {
  claim: ClaimDetail;
  error?: string;
  running: boolean;
  onChanged: () => void;
}) {
  const user = useUser();
  const [action, setAction] = useState<ClaimAction | null>(null);
  const status = statusEntry(claim.status);
  const queue = queueEntry(claim.queue);
  const type = categoryEntry(CLAIM_TYPE, claim.claim_type);
  const inReview = claim.status === "IN_REVIEW";
  const notInReview = `Available while the claim is in review. Status now: ${status.label}.`;
  const seniorQueue = claim.queue === "senior" || claim.queue === "fraud_review";
  const seniorOnly = seniorQueue && user.role !== "senior";
  const seniorReason = seniorOnly ? "Claims in this queue need a senior handler." : null;
  const stale = inReview && claim.needs_reassessment;
  const decide = !inReview ? notInReview : seniorReason;
  const payout = claim.assessment?.total_payout_eur ?? null;
  const claimed = claim.facts?.claimed_total_eur ?? null;
  const back = claim.queue && inReview ? `/?tab=${claim.queue}` : "/";

  return (
    <header className="border-b border-line bg-[#faf9f6] px-6 pb-4 pt-4">
      <div className="flex items-start gap-6">
        <div className="min-w-0 flex-1">
          <Link
            href={back}
            className="inline-flex items-center gap-1 text-[13px] text-ink-3 transition hover:text-ink"
          >
            <ArrowLeft className="size-3.5" aria-hidden /> Queue
          </Link>
          <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
            <h1 className="font-mono text-[22px] font-medium tracking-tight">{claim.reference}</h1>
            <Chip variant={status.variant} icon={status.icon}>
              {status.label}
            </Chip>
            {queue ? (
              <Chip dot variant={queue.variant}>
                {queue.label}
              </Chip>
            ) : (
              <Chip variant="neutral">Not routed</Chip>
            )}
          </div>
          <dl className="mt-3 grid max-w-[760px] grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))] gap-4">
            <Meta label="Insured">{claim.insured ?? <span className="text-ink-3">Unknown</span>}</Meta>
            <Meta label="Product">{claim.product ? humanize(claim.product) : <span className="text-ink-3">–</span>}</Meta>
            <Meta label="Claim type">{type ? type.label : <span className="text-ink-3">–</span>}</Meta>
            <Meta label="Policy">
              <span className="font-mono text-[12.5px]">{claim.policy_number ?? "–"}</span>
            </Meta>
            <Meta label="Core claim">
              <span className="font-mono text-[12.5px]">{claim.core_claim_id ?? "–"}</span>
            </Meta>
          </dl>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-3">
          <div className="text-right">
            <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">Payout</p>
            <p className="tnum text-[26px] font-semibold leading-tight tracking-tight">
              {payout !== null ? eur(payout) : <span className="text-ink-3">–</span>}
            </p>
            <p className="tnum text-xs text-ink-2">{claimed !== null ? `Claimed ${eur(claimed)}` : "Not assessed yet"}</p>
          </div>
          <div className="flex items-center gap-2">
            {claim.status === "FAILED" ? (
              <ActionButton
                label="Retry"
                icon={RotateCcw}
                hint="Run the pipeline again from the start."
                disabledReason={null}
                onClick={() => setAction("retry")}
              />
            ) : null}
            {stale ? (
              <ActionButton
                label="Reassess"
                icon={RefreshCw}
                hint="Fields were corrected after the assessment."
                disabledReason={null}
                onClick={() => setAction("reassess")}
              />
            ) : null}
            <ActionButton
              label="Reject"
              icon={Ban}
              variant="danger"
              disabledReason={decide}
              onClick={() => setAction("reject")}
            />
            <ActionButton
              label="Escalate"
              icon={ArrowUpRight}
              disabledReason={!inReview ? notInReview : seniorQueue ? "Already in a senior queue." : null}
              onClick={() => setAction("escalate")}
            />
            <ActionButton
              label="Request information"
              icon={CircleHelp}
              disabledReason={decide}
              onClick={() => setAction("request-info")}
            />
            <ActionButton
              label="Approve"
              icon={seniorOnly ? Lock : Check}
              variant="approve"
              disabledReason={decide ?? (stale ? "Reassess first: fields were corrected after the assessment." : null)}
              onClick={() => setAction("approve")}
            />
          </div>
        </div>
      </div>

      {claim.error ? (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-800">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <Tooltip content={firstLine(claim.error, 800)} className="min-w-0">
            <span className="block truncate font-mono text-[12px]">{firstLine(claim.error, 200)}</span>
          </Tooltip>
        </div>
      ) : null}
      {running ? (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-line bg-sheet px-3 py-2 text-[13px] text-ink-2">
          <LoaderCircle className="size-4 animate-spin text-ink-3" aria-hidden />
          The pipeline is still working on this claim. This page reloads every 10 seconds.
        </div>
      ) : null}
      {error ? <p className="mt-2 text-xs text-red-700">Reload failed: {error}</p> : null}

      <ActionDialog
        claim={claim}
        action={action}
        onClose={() => setAction(null)}
        onDone={() => {
          setAction(null);
          onChanged();
        }}
      />
    </header>
  );
}

function ActionButton({
  label,
  icon: Icon,
  variant = "outline",
  disabledReason,
  hint,
  onClick,
}: {
  label: string;
  icon: typeof Check;
  variant?: "outline" | "danger" | "approve";
  disabledReason: string | null;
  hint?: string;
  onClick: () => void;
}) {
  const button = (
    <Button variant={variant} size="sm" disabled={disabledReason !== null} onClick={onClick}>
      <Icon aria-hidden />
      {label}
    </Button>
  );
  const tip = disabledReason ?? hint;
  return tip ? (
    <Tooltip content={tip} side="bottom">
      <span>{button}</span>
    </Tooltip>
  ) : (
    button
  );
}
