"use client";

import { Alert, Button, Dialog, Reveal, Textarea, useReplay, useToast } from "@crm-ui/react";
import { useState } from "react";

import { ApiError, api, errorMessage } from "@/lib/api";
import { statusEntry } from "@/lib/enums";
import { eur } from "@/lib/format";
import { DONE_MS, reducedMotion } from "@/lib/motion";
import type { ClaimAction, ClaimDetail } from "@/lib/types";

const COPY: Record<
  ClaimAction,
  { title: string; confirm: string; variant: "approve" | "primary" | "danger"; done: string }
> = {
  approve: { title: "Approve", confirm: "Approve", variant: "approve", done: "approved" },
  "request-info": {
    title: "Request information for",
    confirm: "Request information",
    variant: "primary",
    done: "moved to Needs info",
  },
  escalate: { title: "Escalate", confirm: "Escalate", variant: "primary", done: "moved to the senior queue" },
  reject: { title: "Reject", confirm: "Reject", variant: "danger", done: "rejected" },
  reassess: { title: "Reassess", confirm: "Reassess", variant: "primary", done: "sent back for reassessment" },
  retry: { title: "Retry", confirm: "Retry", variant: "primary", done: "sent back to the pipeline" },
};

function consequence(action: ClaimAction, claim: ClaimDetail): string {
  const payout = claim.assessment?.total_payout_eur;
  switch (action) {
    case "approve":
      return payout
        ? `The claim is submitted to the core system with a payout of ${eur(payout)}.`
        : "The claim is submitted to the core system. No payout has been computed.";
    case "request-info":
      return "The claim moves to Needs info and waits for the client.";
    case "escalate":
      return "The claim moves to the senior queue. Only a senior handler can decide on it there.";
    case "reject":
      return "The claim is closed without a payout.";
    case "retry":
      return "The claim starts over from reading its documents. Use it after the cause of the failure is fixed.";
    case "reassess":
      return "Routing, coverage, payout and letters are computed again from the corrected fields. Extraction does not run again, so your corrections stay.";
  }
}

export function ActionDialog({
  claim,
  action,
  onClose,
  onDone,
}: {
  claim: ClaimDetail;
  action: ClaimAction | null;
  onClose: () => void;
  onDone: () => void;
}) {
  return (
    <CaseActionDialog
      reference={claim.reference}
      action={action}
      consequence={action ? consequence(action, claim) : undefined}
      run={(a, note) => api.act(claim.id, a, claim.version, note)}
      onClose={onClose}
      onDone={onDone}
    />
  );
}

/** Confirmation with an optional note for a claim or invoice action; shows 403/409 refusals in place. */
export function CaseActionDialog({
  reference,
  action,
  consequence: description,
  done: doneCopy,
  run,
  onClose,
  onDone,
}: {
  reference: string;
  action: ClaimAction | null;
  consequence?: string;
  /** Overrides the toast wording per action ("approved", "moved to Needs info"). */
  done?: Partial<Record<ClaimAction, string>>;
  run: (action: ClaimAction, note: string) => Promise<{ status: string }>;
  onClose: () => void;
  onDone: () => void;
}) {
  const notify = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [refused, setRefused] = useState(0);
  const [shownFor, setShownFor] = useState<ClaimAction | null>(null);
  const shake = useReplay(refused);

  // Fresh form each time the dialog opens for an action.
  if (action !== shownFor) {
    setShownFor(action);
    setNote("");
    setProblem(null);
    setBusy(false);
    setDone(false);
  }

  const copy = action ? COPY[action] : null;

  async function confirm() {
    if (!action) return;
    setBusy(true);
    setProblem(null);
    try {
      const res = await run(action, note);
      const s = statusEntry(res.status).label;
      notify("success", `${reference} ${doneCopy?.[action] ?? COPY[action].done}`, `Status: ${s}.`);
      // The confirm button turns into a check for a moment before the dialog leaves: the decision went through.
      setDone(true);
      await new Promise((r) => window.setTimeout(r, reducedMotion() ? 0 : DONE_MS));
      onDone();
    } catch (err) {
      const msg = errorMessage(err);
      const prefix = err instanceof ApiError && (err.status === 403 || err.status === 409) ? `${err.status}: ` : "";
      setProblem(`${prefix}${msg.charAt(0).toUpperCase()}${msg.slice(1)}`);
      setRefused((n) => n + 1);
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={action !== null}
      onClose={busy ? () => undefined : onClose}
      title={copy ? `${copy.title} ${reference}?` : ""}
      description={description}
      footer={
        copy ? (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant={copy.variant} onClick={confirm} loading={busy && !done} done={done} disabled={done}>
              {copy.confirm}
            </Button>
          </>
        ) : null
      }
    >
      <div className="flex flex-col gap-12">
        <Textarea
          id="action-note"
          label="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="Saved in the audit log"
        />
        {/* -mt cancels the flex gap while closed; the padding inside brings it back when open. */}
        <Reveal open={problem !== null} className="-mt-12">
          <div data-shake={shake} className="pt-12">
            <Alert tone="danger" className="items-start">
              {problem}
            </Alert>
          </div>
        </Reveal>
      </div>
    </Dialog>
  );
}
