"use client";

import { Copy, FileText, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { LineTabs, type TabItem } from "@/components/ui/tabs";
import { useNotify } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import { SUMMARY_KIND, statusEntry } from "@/lib/enums";
import type { ClaimStatus, Summary, SummaryKind } from "@/lib/types";

const KINDS: { kind: SummaryKind; lang: string }[] = [
  { kind: "handler", lang: "sk" },
  { kind: "client_letter", lang: "sk" },
  { kind: "group", lang: "de" },
  { kind: "info_request", lang: "sk" },
];

export function TextsPanel({ summaries, status }: { summaries: Summary[]; status: ClaimStatus }) {
  const notify = useNotify();
  const firstPresent = KINDS.find((k) => summaries.some((s) => s.kind === k.kind))?.kind ?? "handler";
  const [picked, setPicked] = useState<SummaryKind | null>(null);
  const kind = picked ?? firstPresent;

  if (summaries.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        compact
        title="No texts yet."
        description={`Summaries and letters are written after assessment. Status now: ${statusEntry(status).label}.`}
      />
    );
  }

  const tabs: TabItem<SummaryKind>[] = KINDS.map(({ kind: k, lang }) => {
    const s = summaries.find((x) => x.kind === k);
    return {
      key: k,
      label: `${SUMMARY_KIND[k]} (${(s?.language ?? lang).toUpperCase()})`,
      flag: s && s.fact_violations.length > 0 ? "danger" : undefined,
    };
  });

  const summary = summaries.find((s) => s.kind === kind);

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      notify("success", "Text copied");
    } catch {
      notify("danger", "Copy failed", "The browser blocked clipboard access.");
    }
  }

  return (
    <div className="px-5 py-3">
      <LineTabs tabs={tabs} value={kind} onChange={setPicked} label="Texts" />
      {!summary || !summary.text ? (
        <p className="py-6 text-sm text-ink-3">No {SUMMARY_KIND[kind]!.toLowerCase()} for this claim.</p>
      ) : (
        <div className="mt-4">
          {summary.fact_violations.length > 0 ? (
            <div className="mb-3 rounded-xl border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-[13px] text-amber-900">
              <p className="flex items-center gap-2 font-medium">
                <TriangleAlert className="size-4" aria-hidden />
                The fact check flagged {summary.fact_violations.length}{" "}
                {summary.fact_violations.length === 1 ? "statement" : "statements"} that do not match the decision.
              </p>
              <ul className="mt-1.5 flex flex-col gap-1 pl-6">
                {summary.fact_violations.map((v, i) => (
                  <li key={i} className="list-disc">
                    <span className="font-mono text-[11.5px] uppercase text-amber-800">{v.kind}</span>{" "}
                    <span>{v.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <article className="group relative rounded-xl border border-line bg-[#fffdf8] px-6 py-5 shadow-[0_1px_2px_rgb(0_0_0/0.04)]">
            <Tooltip content="Copy text" className="absolute right-3 top-3">
              <button
                type="button"
                onClick={() => copy(summary.text!)}
                aria-label="Copy text"
                className="rounded-md p-1.5 text-ink-3 opacity-0 transition hover:bg-black/5 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Copy className="size-4" />
              </button>
            </Tooltip>
            <p lang={summary.language} className="whitespace-pre-wrap font-serif text-[14.5px] leading-[1.7]">
              {summary.text}
            </p>
          </article>
        </div>
      )}
    </div>
  );
}
