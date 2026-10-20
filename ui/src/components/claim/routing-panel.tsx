import { DetailCard, EmptyState, InsightCard, Tag } from "@claimpilot/ui";

import { queueEntry, statusEntry } from "@/lib/enums";
import type { ClaimStatus, Routing } from "@/lib/types";

/** Titled block inside the claim side panel, in the popover-section style (DF 2:1078). */
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
    <section className="flex flex-col gap-12 px-20 py-16 hairline-b last:shadow-none">
      <div className="flex items-center justify-between gap-12">
        <h3 className="cp-text-label text-ink-subtle">{title}</h3>
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
        icon="route"
        title="Not routed yet."
        description={`Routing runs after extraction. Status now: ${statusEntry(status).label}.`}
      />
    );
  }
  const queue = queueEntry(routing.queue);
  return (
    <div>
      <PanelSection title="Decision">
        <DetailCard
          rows={[
            {
              label: "Queue",
              value: queue ? (
                <Tag tone={queue.tone} dot size="md">
                  {queue.label}
                </Tag>
              ) : (
                <span className="text-ink-subtle">None</span>
              ),
            },
            {
              label: "Decided by",
              value: routing.llm_used ? (
                <Tag tone="purple" icon="bot" size="md">
                  Rules and LLM
                </Tag>
              ) : (
                <Tag tone="neutral" icon="check-list" size="md">
                  Rules only
                </Tag>
              ),
            },
          ]}
        />
      </PanelSection>

      <PanelSection title={`Rule hits (${routing.rule_hits.length})`}>
        {routing.rule_hits.length === 0 ? (
          <p className="cp-text-cell text-ink-subtle">No rules fired.</p>
        ) : (
          <ul className="flex flex-col gap-8">
            {routing.rule_hits.map((h, i) => (
              <li key={`${h.rule}-${i}`}>
                <InsightCard
                  priority={h.rule === "R10" ? { label: `${h.rule} · Urgent`, tone: "danger" } : { label: h.rule, tone: "neutral" }}
                  title={h.detail}
                />
              </li>
            ))}
          </ul>
        )}
      </PanelSection>

      <PanelSection title="Rationale">
        {routing.rationale ? (
          <p className="cp-text-cell whitespace-pre-wrap text-ink-cell">{routing.rationale}</p>
        ) : (
          <p className="cp-text-cell text-ink-subtle">No rationale recorded.</p>
        )}
      </PanelSection>
    </div>
  );
}
