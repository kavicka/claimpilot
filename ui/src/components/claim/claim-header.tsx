"use client";

import { Alert, AppHeader, Button, Crumbs, RecordNav, Reveal, SplitButton, Tag, Tooltip, useReplay, type ButtonVariant, type IconName } from "@crm-ui/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useUser } from "@/components/shell/auth";
import { CLAIM_TYPE, categoryEntry, queueEntry, statusEntry } from "@/lib/enums";
import { eur, firstLine, humanize } from "@/lib/format";
import type { ClaimAction, ClaimDetail } from "@/lib/types";

import { ActionDialog } from "./action-dialog";

export interface QueueNav {
  prev?: { href: string; label: string };
  next?: { href: string; label: string };
  /** "3 of 12 in Fast track". */
  position?: string;
}

/** Label and value in the claim summary, in the drawer's detail-card style (DF 2:548). */
export function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <dt className="cp-text-label text-ink-subtle">{label}</dt>
      <dd className="cp-text-cell truncate text-ink-cell">{children}</dd>
    </div>
  );
}

export function ClaimHeader({
  claim,
  error,
  running,
  onChanged,
  nav,
}: {
  claim: ClaimDetail;
  error?: string;
  running: boolean;
  onChanged: () => void;
  /** Neighbours in the queue tab the handler came from. */
  nav?: QueueNav;
}) {
  const user = useUser();
  const router = useRouter();
  const [action, setAction] = useState<ClaimAction | null>(null);
  // "Approve and open next": after the decision goes through, go straight to the next claim in the queue.
  const [thenNext, setThenNext] = useState(false);
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
  const queueLabel = queue?.label ?? "Queue";

  // Cues for changes while the page is open (an action, a poll): never on first paint.
  const statusCue = useReplay(claim.status);
  const payoutCue = useReplay(payout);
  // Previous values kept in state (React's "adjust state while rendering" pattern).
  const [seenPayout, setSeenPayout] = useState(payout);
  const [payoutUp, setPayoutUp] = useState(true);
  if (seenPayout !== payout) {
    setPayoutUp(Number(payout ?? 0) >= Number(seenPayout ?? 0));
    setSeenPayout(payout);
  }
  // Approve unlocks after a reassessment: one soft ring says "now you can approve".
  const [unlocked, setUnlocked] = useState(0);
  const [wasStale, setWasStale] = useState(stale);
  if (wasStale !== stale) {
    if (wasStale && !stale && inReview) setUnlocked((n) => n + 1);
    setWasStale(stale);
  }
  const approveCue = useReplay(unlocked);

  return (
    <header className="shrink-0">
      <AppHeader
        crumbs={<Crumbs items={[{ label: "Claims", href: "/" }, { label: queueLabel, href: back }, { label: claim.reference }]} onCopy={() => navigator.clipboard?.writeText(claim.reference)} />}
        meta={running ? "Refreshes every 10 seconds" : undefined}
        actions={nav ? <RecordNav prev={nav.prev} next={nav.next} position={nav.position} /> : undefined}
      />

      <div className="flex items-start gap-24 px-24 pb-16 pt-20 hairline-b">
        <div className="flex min-w-0 flex-1 flex-col gap-14">
          <div className="flex flex-wrap items-center gap-10">
            <h1 className="cp-text-title-xl text-ink">{claim.reference}</h1>
            <span key={claim.status} data-pop={statusCue} className="inline-flex">
              <Tag tone={status.tone} icon={status.icon ?? null} size="md">
                {status.label}
              </Tag>
            </span>
            {queue ? (
              <Tag tone={queue.tone} dot size="md">
                {queue.label}
              </Tag>
            ) : (
              <Tag tone="neutral" size="md">
                Not routed
              </Tag>
            )}
          </div>
          <dl className="grid max-w-[47.5rem] grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))] gap-16">
            <Meta label="Insured">{claim.insured ?? <span className="text-ink-subtle">Unknown</span>}</Meta>
            <Meta label="Product">{claim.product ? humanize(claim.product) : "–"}</Meta>
            <Meta label="Claim type">{type ? type.label : "–"}</Meta>
            <Meta label="Policy">{claim.policy_number ?? "–"}</Meta>
            <Meta label="Core claim">{claim.core_claim_id ?? "–"}</Meta>
          </dl>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-12">
          <div className="flex flex-col items-end gap-2">
            <p className="cp-text-label text-ink-subtle">Payout</p>
            <p
              className={`cp-text-stat-xl tnum rounded-(--radius-6) px-4 text-ink ${payoutUp ? "cp-flash--ok" : ""}`}
              data-flash={payoutCue}
            >
              <span data-tick={payoutCue}>{payout !== null ? eur(payout) : "–"}</span>
            </p>
            <p className="cp-text-meta tnum text-ink-subtle">{claimed !== null ? `Claimed ${eur(claimed)}` : "Not assessed yet"}</p>
          </div>
          <div className="flex items-center gap-8">
            {claim.status === "FAILED" ? (
              <ActionButton label="Retry" icon="retry" hint="Run the pipeline again from the start." disabledReason={null} onClick={() => setAction("retry")} />
            ) : null}
            {stale ? (
              <ActionButton
                label="Reassess"
                icon="refresh"
                hint="Fields were corrected after the assessment."
                disabledReason={null}
                onClick={() => setAction("reassess")}
              />
            ) : null}
            <ActionButton label="Reject" icon="ban" variant="danger" disabledReason={decide} onClick={() => setAction("reject")} />
            <ActionButton
              label="Escalate"
              icon="arrow-up-right"
              disabledReason={!inReview ? notInReview : seniorQueue ? "Already in a senior queue." : null}
              onClick={() => setAction("escalate")}
            />
            <ActionButton label="Request information" icon="help-circle" disabledReason={decide} onClick={() => setAction("request-info")} />
            {decide ?? stale ? (
              <ActionButton
                label="Approve"
                icon={seniorOnly ? "lock" : "check"}
                variant="approve"
                disabledReason={decide ?? (stale ? "Reassess first: fields were corrected after the assessment." : null)}
                onClick={() => setAction("approve")}
                cue={approveCue}
              />
            ) : (
              <span className="inline-flex rounded-(--radius-8)" data-pulse={approveCue}>
                <SplitButton
                  variant="approve"
                  icon="check"
                  menuLabel="Other ways to decide"
                  onClick={() => {
                    setThenNext(false);
                    setAction("approve");
                  }}
                  items={[
                    {
                      label: nav?.next ? `Approve and open ${nav.next.label}` : "Approve and open next (last in queue)",
                      icon: "arrow-up-right",
                      disabled: !nav?.next,
                      onSelect: () => {
                        setThenNext(true);
                        setAction("approve");
                      },
                    },
                  ]}
                >
                  Approve
                </SplitButton>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Banners open and close by height, so the panes below move instead of jumping when the pipeline finishes. */}
      <Reveal open={Boolean(claim.error || running || error)}>
        {/* Spacing sits on the alerts (mt-8), not in a flex gap, so closed banners take no room. */}
        <div className="flex flex-col px-24 pb-10 pt-2 hairline-b">
          <Reveal open={Boolean(claim.error)}>
            {claim.error ? (
              <Alert tone="danger" className="mt-8">
                <Tooltip content={firstLine(claim.error, 800)} className="w-full">
                  <span className="block truncate">{firstLine(claim.error, 200)}</span>
                </Tooltip>
              </Alert>
            ) : null}
          </Reveal>
          <Reveal open={running}>
            <Alert tone="info" className="mt-8">
              The pipeline is still working on this claim. This page reloads every 10 seconds.
            </Alert>
          </Reveal>
          <Reveal open={Boolean(error)}>{error ? (
              <Alert tone="warning" className="mt-8">
                Reload failed: {error}
              </Alert>
            ) : null}</Reveal>
        </div>
      </Reveal>

      <ActionDialog
        claim={claim}
        action={action}
        onClose={() => setAction(null)}
        onDone={() => {
          setAction(null);
          if (thenNext && nav?.next?.href) router.push(nav.next.href);
          else onChanged();
        }}
      />
    </header>
  );
}

export function ActionButton({
  label,
  icon,
  variant = "secondary",
  disabledReason,
  hint,
  onClick,
  cue,
}: {
  label: string;
  icon: IconName;
  variant?: ButtonVariant;
  disabledReason: string | null;
  hint?: string;
  onClick: () => void;
  /** Flip to play the "now available" ring (useReplay). */
  cue?: "a" | "b";
}) {
  const button = (
    <Button variant={variant} icon={icon} disabled={disabledReason !== null} onClick={onClick} data-pulse={cue}>
      {label}
    </Button>
  );
  const tip = disabledReason ?? hint;
  return tip ? (
    <Tooltip content={tip} side="bottom">
      {button}
    </Tooltip>
  ) : (
    button
  );
}
