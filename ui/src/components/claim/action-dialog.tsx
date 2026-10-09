"use client";

import { LoaderCircle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useNotify } from "@/components/ui/toast";
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
  const notify = useNotify();
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
      const res = await api.act(claim.id, action, note);
      const s = statusEntry(res.status).label;
      notify("success", `${claim.reference} ${COPY[action].done}`, `Status: ${s}.`);
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
      title={copy ? `${copy.title} ${claim.reference}?` : ""}
      description={action ? consequence(action, claim) : undefined}
      footer={
        copy ? (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant={copy.variant} onClick={confirm} disabled={busy}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
              {copy.confirm}
            </Button>
          </>
        ) : null
      }
    >
      <label htmlFor="action-note" className="block text-[13px] font-medium">
        Note <span className="font-normal text-ink-3">(optional)</span>
      </label>
      <textarea
        id="action-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
        placeholder="Saved in the audit log"
        className="mt-1.5 w-full resize-y rounded-lg border border-line-2 bg-white px-3 py-2 text-sm outline-none transition placeholder:text-ink-3 focus:border-ink focus:ring-2 focus:ring-ink/10"
      />
      {problem ? (
        <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {problem}
        </p>
      ) : null}
    </Dialog>
  );
}
