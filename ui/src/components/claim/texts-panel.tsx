"use client";

import { EmptyState, Icon, IconButton, RecommendationCard, Tabs, Tooltip, useToast, type TabItem } from "@crm-ui/react";
import { useState } from "react";

import { SUMMARY_KIND, statusEntry } from "@/lib/enums";
import type { ClaimStatus, Summary, SummaryKind } from "@/lib/types";

const KINDS: { kind: SummaryKind; lang: string }[] = [
  { kind: "handler", lang: "sk" },
  { kind: "client_letter", lang: "sk" },
  { kind: "group", lang: "de" },
  { kind: "info_request", lang: "sk" },
];

export function TextsPanel({ summaries, status }: { summaries: Summary[]; status: ClaimStatus }) {
  const notify = useToast();
  const firstPresent = KINDS.find((k) => summaries.some((s) => s.kind === k.kind))?.kind ?? "handler";
  const [picked, setPicked] = useState<SummaryKind | null>(null);
  const kind = picked ?? firstPresent;

  if (summaries.length === 0) {
    return (
      <EmptyState
        icon="file-text"
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
  const letter = summaries.find((s) => s.kind === "client_letter" && s.text);
  const showReco = status === "IN_REVIEW" && letter && kind !== "client_letter";

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      notify("success", "Text copied");
    } catch {
      notify("danger", "Copy failed", "The browser blocked clipboard access.");
    }
  }

  return (
    <div className="flex flex-col gap-16 px-20 py-12">
      {showReco ? (
        <RecommendationCard
          label="Before you approve"
          title="Read the client letter"
          reason={
            letter.fact_violations.length > 0
              ? `The fact check flagged ${letter.fact_violations.length} ${letter.fact_violations.length === 1 ? "statement" : "statements"} in it.`
              : "It goes to the client with the decision. The fact check found nothing to fix."
          }
          draft={{
            title: `${SUMMARY_KIND.client_letter} (${letter.language.toUpperCase()})`,
            detail: (letter.text ?? "").split("\n", 1)[0]?.slice(0, 90),
            review: { label: "Review", onClick: () => setPicked("client_letter") },
          }}
        />
      ) : null}
      <Tabs variant="line" tabs={tabs} value={kind} onValueChange={setPicked} label="Texts" />
      {!summary || !summary.text ? (
        <p className="cp-text-cell py-24 text-ink-subtle">No {SUMMARY_KIND[kind]!.toLowerCase()} for this claim.</p>
      ) : (
        <div className="flex flex-col gap-12">
          {summary.fact_violations.length > 0 ? (
            <div className="flex animate-rise flex-col gap-6 rounded-(--radius-12) bg-warning-bg px-12 py-10 text-warning-ink" role="status">
              <p className="cp-text-tab flex items-center gap-8">
                <Icon name="warning" size={16} />
                The fact check flagged {summary.fact_violations.length}{" "}
                {summary.fact_violations.length === 1 ? "statement" : "statements"} that do not match the decision.
              </p>
              <ul className="cp-text-label-regular flex list-disc flex-col gap-4 pl-40">
                {summary.fact_violations.map((v, i) => (
                  <li key={i}>
                    <span className="uppercase">{v.kind}</span> <span>{v.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <article className="group relative rounded-(--radius-12) bg-surface px-24 py-20 hairline">
            <Tooltip content="Copy text" className="absolute right-12 top-12">
              <IconButton
                variant="outline"
                icon="copy"
                iconSize={14}
                label="Copy text"
                onClick={() => copy(summary.text!)}
                className="opacity-0 transition-opacity duration-(--cp-dur-1) focus-visible:opacity-100 group-hover:opacity-100"
              />
            </Tooltip>
            <p lang={summary.language} className="cp-text-message-body whitespace-pre-wrap text-ink-strong">
              {summary.text}
            </p>
          </article>
        </div>
      )}
    </div>
  );
}
