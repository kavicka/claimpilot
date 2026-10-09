import { Bot, ListChecks, Route } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { queueEntry, statusEntry } from "@/lib/enums";
import type { ClaimStatus, Routing } from "@/lib/types";

export function PanelSection({
  title,
  children,
  trailing,
}: {
  title: string;
  children: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <section className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-3">{title}</h3>
        {trailing}
      </div>
      {children}
    </section>
  );
}

export function RoutingPanel({ routing, status }: { routing: Routing | null; status: ClaimStatus }) {
  if (!routing) {
    return (
      <EmptyState
        icon={Route}
        compact
        title="Not routed yet."
        description={`Routing runs after extraction. Status now: ${statusEntry(status).label}.`}
      />
    );
  }
  const queue = queueEntry(routing.queue);
  return (
    <div>
      <PanelSection title="Decision">
        <dl className="grid grid-cols-2 gap-4">
          <div>
            <dt className="text-xs text-ink-3">Queue</dt>
            <dd className="mt-1">
              {queue ? (
                <Chip dot variant={queue.variant}>
                  {queue.label}
                </Chip>
              ) : (
                <span className="text-sm text-ink-3">None</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Decided by</dt>
            <dd className="mt-1">
              {routing.llm_used ? (
                <Chip variant="purple" icon={Bot}>
                  Rules and LLM
                </Chip>
              ) : (
                <Chip variant="neutral" icon={ListChecks}>
                  Rules only
                </Chip>
              )}
            </dd>
          </div>
        </dl>
      </PanelSection>

      <PanelSection title={`Rule hits (${routing.rule_hits.length})`}>
        {routing.rule_hits.length === 0 ? (
          <p className="text-sm text-ink-2">No rules fired.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {routing.rule_hits.map((h, i) => (
              <li key={`${h.rule}-${i}`} className="flex items-start gap-2.5">
                <Chip mono variant="neutral" className="mt-px">
                  {h.rule}
                </Chip>
                <span className="text-[13px] leading-snug">{h.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </PanelSection>

      <PanelSection title="Rationale">
        {routing.rationale ? (
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{routing.rationale}</p>
        ) : (
          <p className="text-sm text-ink-3">No rationale recorded.</p>
        )}
      </PanelSection>
    </div>
  );
}
