"use client";

import { LoaderCircle } from "lucide-react";

import { Dialog } from "@/components/ui/dialog";
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
          <span className="flex items-baseline gap-2">
            <span>{data.display}</span>
            <span className="font-mono text-xs font-normal text-ink-3">{data.clause_id}</span>
          </span>
        ) : (
          <span className="font-mono">{clauseId}</span>
        )
      }
      description={data?.heading}
    >
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-ink-2">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Loading clause
        </p>
      ) : error ? (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          Clause {clauseId} could not be loaded: {error}
        </p>
      ) : data ? (
        <p lang="sk" className="whitespace-pre-wrap font-serif text-[15px] leading-relaxed">
          {data.text}
        </p>
      ) : null}
    </Dialog>
  );
}
