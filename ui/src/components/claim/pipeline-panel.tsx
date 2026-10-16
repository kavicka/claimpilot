import { EmptyState, Icon, InlineLink, Tag, type IconName } from "@claimpilot/ui";

import { cn } from "@/lib/cn";
import { duration, firstLine, humanize, int, when } from "@/lib/format";
import type { AuditEntry, StepRun } from "@/lib/types";

import { PanelSection } from "./routing-panel";

const STEP_ICON: Record<string, { icon: IconName; className: string; label: string }> = {
  ok: { icon: "check-circle", className: "text-activity-success", label: "Succeeded" },
  error: { icon: "alert-circle", className: "text-danger-ink", label: "Failed" },
};

function auditDetails(details: AuditEntry["details"]): string | null {
  if (!details) return null;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(details)) {
    if (v === null || v === undefined || v === "") continue;
    if (k === "note") parts.push(`“${String(v)}”`);
    else if (k === "field") parts.push(String(v));
    else if (k === "document_id") continue;
    else parts.push(`${humanize(k)}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

export function PipelinePanel({
  steps,
  audit,
  traceUrl,
}: {
  steps: StepRun[];
  audit: AuditEntry[];
  traceUrl: string | null;
}) {
  const totalMs = steps.reduce((n, s) => n + (s.status === "ok" ? (s.latency_ms ?? 0) : 0), 0);
  const totalTokens = steps.reduce((n, s) => n + s.tokens, 0);

  return (
    <div>
      <PanelSection
        title={`Steps (${steps.length})`}
        trailing={
          traceUrl ? (
            <InlineLink href={traceUrl} target="_blank" rel="noreferrer" className="cp-text-label inline-flex items-center gap-4">
              Langfuse trace <Icon name="external-link" size={12} />
            </InlineLink>
          ) : (
            <span className="cp-text-meta text-ink-subtle">No trace</span>
          )
        }
      >
        {steps.length === 0 ? (
          <EmptyState icon="workflow" title="No pipeline steps recorded." />
        ) : (
          <>
            <p className="cp-text-label-regular text-ink-subtle">
              <span className="tnum">{duration(totalMs)}</span> in successful steps ·{" "}
              <span className="tnum">{int(totalTokens)}</span> tokens
            </p>
            {/* Timeline rail and spacing from the drawer (DF 2:513); the step icon says how it ended. */}
            <ol className="cp-timeline">
              {steps.map((s, i) => {
                const mark = STEP_ICON[s.status] ?? { icon: "circle-dashed" as const, className: "text-ink-subtle", label: humanize(s.status) };
                return (
                  <li key={i} className="cp-timeline__item pb-14" style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
                    <span className={cn("cp-timeline__icon", mark.className)}>
                      <Icon name={mark.icon} size={16} label={mark.label} />
                    </span>
                    <div className="flex min-w-0 flex-col gap-4">
                      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
                        <span className="cp-text-tab text-ink">{s.step}</span>
                        {s.attempt > 1 ? <Tag tone="warning">Attempt {s.attempt}</Tag> : null}
                        {s.status !== "ok" ? <Tag tone={s.status === "error" ? "danger" : "neutral"}>{humanize(s.status)}</Tag> : null}
                        <span className="cp-text-meta tnum ml-auto text-ink-subtle">
                          {duration(s.latency_ms)}
                          {s.tokens ? ` · ${int(s.tokens)} tokens` : ""}
                        </span>
                      </div>
                      {s.models.length ? (
                        <div className="flex flex-wrap gap-4">
                          {s.models.map((m) => (
                            <Tag key={m} tone="neutral">
                              {m}
                            </Tag>
                          ))}
                        </div>
                      ) : null}
                      {s.error ? (
                        <details className="cp-text-label-regular rounded-(--radius-8) bg-danger-bg text-danger-ink">
                          <summary className="cursor-pointer truncate px-10 py-6">{firstLine(s.error, 120)}</summary>
                          <pre className="pane-scroll max-h-[224px] overflow-auto whitespace-pre-wrap break-all px-10 py-8 font-num hairline-t">
                            {s.error}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </PanelSection>

      <PanelSection title={`Audit log (${audit.length})`}>
        {audit.length === 0 ? (
          <EmptyState icon="history" title="No handler actions yet." />
        ) : (
          <ul className="flex flex-col">
            {[...audit].reverse().map((a, i) => {
              const details = auditDetails(a.details);
              return (
                <li key={i} className="flex items-baseline gap-12 py-8 hairline-b last:shadow-none">
                  <span className="cp-text-tab text-ink">{humanize(a.action.replace(/-/g, "_"))}</span>
                  <span className="cp-text-cell min-w-0 flex-1 truncate text-ink-subtle">{details ?? ""}</span>
                  <span className="cp-text-meta tnum shrink-0 text-ink-subtle">{when(a.at)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </PanelSection>
    </div>
  );
}
