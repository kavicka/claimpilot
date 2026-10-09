import { ExternalLink, History, Workflow } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/cn";
import { duration, firstLine, humanize, int, when } from "@/lib/format";
import type { AuditEntry, StepRun } from "@/lib/types";

import { PanelSection } from "./routing-panel";

const STEP_DOT: Record<string, string> = {
  ok: "bg-emerald-500 ring-emerald-100",
  error: "bg-red-500 ring-red-100",
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
            <a
              href={traceUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-ink underline-offset-2 hover:underline"
            >
              Langfuse trace <ExternalLink className="size-3.5" aria-hidden />
            </a>
          ) : (
            <span className="text-xs text-ink-3">No trace</span>
          )
        }
      >
        {steps.length === 0 ? (
          <EmptyState icon={Workflow} compact title="No pipeline steps recorded." />
        ) : (
          <>
            <p className="mb-3 text-xs text-ink-2">
              <span className="tnum">{duration(totalMs)}</span> in successful steps ·{" "}
              <span className="tnum">{int(totalTokens)}</span> tokens
            </p>
            <ol className="relative">
              {steps.map((s, i) => (
                <li key={i} className="relative flex gap-3 pb-3.5 last:pb-0">
                  {i < steps.length - 1 ? (
                    <span aria-hidden className="absolute left-[4.5px] top-3.5 h-full w-px bg-line-2" />
                  ) : null}
                  <span
                    aria-hidden
                    className={cn(
                      "relative mt-[5px] size-2.5 shrink-0 rounded-full ring-4",
                      STEP_DOT[s.status] ?? "bg-stone-400 ring-stone-100",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="font-mono text-[13px] font-medium">{s.step}</span>
                      {s.attempt > 1 ? <Chip variant="warning">Attempt {s.attempt}</Chip> : null}
                      {s.status !== "ok" ? (
                        <Chip variant={s.status === "error" ? "danger" : "neutral"}>{humanize(s.status)}</Chip>
                      ) : null}
                      <span className="tnum ml-auto text-xs text-ink-2">
                        {duration(s.latency_ms)}
                        {s.tokens ? ` · ${int(s.tokens)} tokens` : ""}
                      </span>
                    </div>
                    {s.models.length ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {s.models.map((m) => (
                          <span key={m} className="rounded bg-stone-100 px-1.5 py-px font-mono text-[11px] text-ink-2">
                            {m}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {s.error ? (
                      <details className="mt-1.5 rounded-lg border border-red-200 bg-red-50/70 text-xs text-red-800">
                        <summary className="cursor-pointer truncate px-2.5 py-1.5 font-mono">{firstLine(s.error, 120)}</summary>
                        <pre className="pane-scroll max-h-56 overflow-auto whitespace-pre-wrap break-all border-t border-red-200 px-2.5 py-2 font-mono text-[11px]">
                          {s.error}
                        </pre>
                      </details>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </PanelSection>

      <PanelSection title={`Audit log (${audit.length})`}>
        {audit.length === 0 ? (
          <EmptyState icon={History} compact title="No handler actions yet." />
        ) : (
          <ul className="flex flex-col divide-y divide-line">
            {[...audit].reverse().map((a, i) => {
              const details = auditDetails(a.details);
              return (
                <li key={i} className="flex items-baseline gap-3 py-2 first:pt-0">
                  <span className="text-[13px] font-medium">{humanize(a.action.replace(/-/g, "_"))}</span>
                  {details ? <span className="min-w-0 flex-1 truncate text-[13px] text-ink-2">{details}</span> : <span className="flex-1" />}
                  <span className="tnum shrink-0 text-xs text-ink-3">{when(a.at)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </PanelSection>
    </div>
  );
}
