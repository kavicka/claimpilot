"use client";

import { Scale } from "lucide-react";
import { useState } from "react";

import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
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
        icon={Scale}
        compact
        title="No coverage decisions yet."
        description={`Assessment runs after routing. Status now: ${statusEntry(status).label}.`}
      />
    );
  }

  return (
    <div>
      <PanelSection title={`Items (${items.length})`}>
        {items.length === 0 ? (
          <p className="text-sm text-ink-2">No claimed items were assessed.</p>
        ) : (
          <ul className="-mx-5 divide-y divide-line">
            {items.map((it) => {
              const section = categoryEntry(COVERAGE, it.coverage);
              const verdict = VERDICT[it.verdict] ?? { label: it.verdict, variant: "neutral" as const };
              return (
                <li key={it.ref} className="px-5 py-3">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <Tooltip content={it.description} className="w-full">
                        <p className="truncate text-[13px] font-medium">{it.description ?? it.ref}</p>
                      </Tooltip>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {section ? (
                          <Chip dot variant={section.variant}>
                            {section.label}
                          </Chip>
                        ) : null}
                        <Chip variant={verdict.variant} icon={verdict.icon}>
                          {verdict.label}
                        </Chip>
                        {it.clauses.map((c) => (
                          <Tooltip key={c} content="Show clause text">
                            <button
                              type="button"
                              onClick={() => setClause(c)}
                              className="rounded-full bg-ink/[0.04] px-2 py-0.5 font-mono text-[11.5px] font-medium text-ink ring-1 ring-inset ring-line-2 transition hover:bg-marker-soft hover:ring-marker-edge"
                            >
                              {c}
                            </button>
                          </Tooltip>
                        ))}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="tnum text-[13px] font-semibold">{eur(it.payout_eur)}</p>
                      <p className="tnum text-[11.5px] text-ink-3">
                        {it.claimed !== null && it.currency ? `of ${money(it.claimed, it.currency)}` : "amount unreadable"}
                      </p>
                    </div>
                  </div>
                  {it.rationale ? (
                    <p className="mt-1.5 text-[12.5px] leading-snug text-ink-2">{it.rationale}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </PanelSection>

      {assessment ? (
        <>
          <PanelSection title="Totals">
            <dl className="grid grid-cols-3 gap-3">
              <Total label="Payout" value={assessment.total_payout_eur} strong />
              <Total label="Deductible" value={assessment.deductible_eur} />
              <Total label="Held" value={assessment.held_eur} />
            </dl>
            {Object.keys(assessment.by_coverage).length > 0 ? (
              <table className="mt-3 w-full text-[13px]">
                <tbody>
                  {Object.entries(assessment.by_coverage).map(([cov, amount]) => {
                    const e = categoryEntry(COVERAGE, cov);
                    return (
                      <tr key={cov} className="border-t border-line/70">
                        <td className="py-1.5 text-ink-2">{e?.label ?? cov}</td>
                        <td className="tnum py-1.5 text-right">{eur(amount)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </PanelSection>
          <PanelSection title="How the payout was computed">
            {assessment.explanation.length === 0 ? (
              <p className="text-sm text-ink-3">No explanation recorded.</p>
            ) : (
              <ol className="flex flex-col gap-1.5">
                {assessment.explanation.map((line, i) => (
                  <li key={i} className="flex gap-2.5 text-[13px] leading-snug">
                    <span className="tnum w-4 shrink-0 text-right font-mono text-[11.5px] text-ink-3">{i + 1}</span>
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

function Total({ label, value, strong = false }: { label: string; value: string | null; strong?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-stone-50/60 px-3 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className={strong ? "tnum mt-0.5 text-[17px] font-semibold" : "tnum mt-0.5 text-[15px]"}>{eur(value)}</dd>
    </div>
  );
}
