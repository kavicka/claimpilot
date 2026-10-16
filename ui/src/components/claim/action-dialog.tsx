"use client";

import { Alert, Button, Dialog, Textarea, useToast } from "@claimpilot/ui";
import { useState } from "react";

import { ApiError, api, errorMessage } from "@/lib/api";
import { statusEntry } from "@/lib/enums";
import { eur } from "@/lib/format";
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
  done,
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
  const [shownFor, setShownFor] = useState<ClaimAction | null>(null);

  // Fresh form each time the dialog opens for an action.
  if (action !== shownFor) {
    setShownFor(action);
    setNote("");
    setProblem(null);
    setBusy(false);
  }

  const copy = action ? COPY[action] : null;

  async function confirm() {
    if (!action) return;
    setBusy(true);
    setProblem(null);
    try {
      const res = await run(action, note);
      const s = statusEntry(res.status).label;
      notify("success", `${reference} ${done?.[action] ?? COPY[action].done}`, `Status: ${s}.`);
      onDone();
    } catch (err) {
      const msg = errorMessage(err);
      const prefix = err instanceof ApiError && (err.status === 403 || err.status === 409) ? `${err.status}: ` : "";
      setProblem(`${prefix}${msg.charAt(0).toUpperCase()}${msg.slice(1)}`);
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
            <Button variant={copy.variant} onClick={confirm} loading={busy}>
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
        {problem ? (
          <Alert tone="danger" className="items-start">
            {problem}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}
