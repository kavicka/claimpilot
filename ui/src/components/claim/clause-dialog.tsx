"use client";

import { Alert, Dialog, Spinner } from "@claimpilot/ui";

import { api } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";

export function ClauseDialog({ clauseId, onClose }: { clauseId: string | null; onClose: () => void }) {
  const { data, error, loading } = useFetch(clauseId ? `clause:${clauseId}` : null, () => api.clause(clauseId ?? ""));

  return (
    <Dialog
      open={clauseId !== null}
      onClose={onClose}
      className="w-[min(600px,calc(100vw-32px))]"
      title={
        data ? (
          <span className="flex items-baseline gap-8">
            <span>{data.display}</span>
            <span className="cp-text-meta text-ink-subtle">{data.clause_id}</span>
          </span>
        ) : (
          clauseId
        )
      }
      description={data?.heading}
    >
      {loading ? (
        <p className="flex items-center gap-8 text-ink-subtle" role="status">
          <Spinner /> Loading clause
        </p>
      ) : error ? (
        <Alert tone="danger">
          Clause {clauseId} could not be loaded: {error}
        </Alert>
      ) : data ? (
        <p lang="sk" className="cp-text-message-body whitespace-pre-wrap text-ink-strong">
          {data.text}
        </p>
      ) : null}
    </Dialog>
  );
}
