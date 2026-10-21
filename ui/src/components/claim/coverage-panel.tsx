"use client";

import { EmptyState, Stat, Tag, Tooltip } from "@crm-ui/react";
import { useState } from "react";

import { COVERAGE, VERDICT, categoryEntry, statusEntry } from "@/lib/enums";
import { eur, money } from "@/lib/format";
import type { Assessment, ClaimStatus, CoverageItem } from "@/lib/types";

import { ClauseDialog } from "./clause-dialog";
import { PanelSection } from "./routing-panel";

export function CoveragePanel({
  items,
  assessment,
  status,
}: {
  items: CoverageItem[];
  assessment: Assessment | null;
  status: ClaimStatus;
}) {
  const [clause, setClause] = useState<string | null>(null);

  if (items.length === 0 && !assessment) {
    return (
      <EmptyState
        icon="scale"
        title="No coverage decisions yet."
        description={`Assessment runs after routing. Status now: ${statusEntry(status).label}.`}
      />
    );
  }

  return (
    <div>
      <PanelSection title={`Items (${items.length})`}>
        {items.length === 0 ? (
          <p className="cp-text-cell text-ink-subtle">No claimed items were assessed.</p>
        ) : (
          <ul className="-mx-20 flex flex-col">
            {items.map((it) => {
              const section = categoryEntry(COVERAGE, it.coverage);
              const verdict = VERDICT[it.verdict] ?? { label: it.verdict, tone: "neutral" as const };
              return (
                <li key={it.ref} className="flex flex-col gap-6 px-20 py-12 hairline-t">
                  <div className="flex items-start gap-12">
                    <div className="flex min-w-0 flex-1 flex-col gap-6">
                      <Tooltip content={it.description} className="w-full">
                        <p className="cp-text-tab truncate text-ink">{it.description ?? it.ref}</p>
                      </Tooltip>
                      <div className="flex flex-wrap items-center gap-6">
                        {section ? (
                          <Tag tone={section.tone} dot size="md">
                            {section.label}
                          </Tag>
                        ) : null}
                        <Tag tone={verdict.tone} icon={verdict.icon ?? null} size="md">
                          {verdict.label}
                        </Tag>
                        {it.clauses.map((c) => (
                          <Tooltip key={c} content="Show clause text">
                            <button type="button" onClick={() => setClause(c)} className="cp-chip">
                              {c}
                            </button>
                          </Tooltip>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <p className="cp-text-tab tnum text-ink">{eur(it.payout_eur)}</p>
                      <p className="cp-text-meta tnum text-ink-subtle">
                        {it.claimed !== null && it.currency ? `of ${money(it.claimed, it.currency)}` : "amount unreadable"}
                      </p>
                    </div>
                  </div>
                  {it.rationale ? <p className="cp-text-label-regular text-ink-subtle">{it.rationale}</p> : null}
                </li>
              );
            })}
          </ul>
        )}
      </PanelSection>

      {assessment ? (
        <>
          <PanelSection title="Totals">
            <div className="grid grid-cols-3 gap-8">
              <Total label="Payout" value={assessment.total_payout_eur} />
              <Total label="Deductible" value={assessment.deductible_eur} />
              <Total label="Held" value={assessment.held_eur} />
            </div>
            {Object.keys(assessment.by_coverage).length > 0 ? (
              <table className="cp-text-cell w-full text-ink-cell">
                <tbody>
                  {Object.entries(assessment.by_coverage).map(([cov, amount]) => {
                    const e = categoryEntry(COVERAGE, cov);
                    return (
                      <tr key={cov} className="hairline-t">
                        <td className="py-6 text-ink-subtle">{e?.label ?? cov}</td>
                        <td className="tnum py-6 text-right">{eur(amount)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </PanelSection>
          <PanelSection title="How the payout was computed">
            {assessment.explanation.length === 0 ? (
              <p className="cp-text-cell text-ink-subtle">No explanation recorded.</p>
            ) : (
              <ol className="flex flex-col gap-6">
                {assessment.explanation.map((line, i) => (
                  <li key={i} className="cp-text-cell flex gap-10 text-ink-cell">
                    <span className="tnum w-16 shrink-0 text-right text-ink-subtle">{i + 1}</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>
            )}
          </PanelSection>
        </>
      ) : null}

      <ClauseDialog clauseId={clause} onClose={() => setClause(null)} />
    </div>
  );
}

function Total({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-(--radius-12) px-12 py-10 hairline">
      <Stat label={label} value={<span className="tnum">{eur(value)}</span>} />
    </div>
  );
}
