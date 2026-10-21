"use client";

import { Alert, EmptyState, InlineLink, Spinner, Tabs, useSwapDirection, useToast, type TabItem } from "@crm-ui/react";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { PIPELINE_STATUSES, queueEntry } from "@/lib/enums";
import type { ClaimDetail, ClaimRow, Field, FieldPatchResult } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

import { ClaimHeader, type QueueNav } from "./claim-header";
import { CoveragePanel } from "./coverage-panel";
import { DocumentViewer } from "./document-viewer";
import { FieldPanel } from "./field-panel";
import { isFlagged } from "./field-utils";
import { InjectionWarning, injectionHits } from "./injection-warning";
import { PipelinePanel } from "./pipeline-panel";
import { RoutingPanel } from "./routing-panel";
import { TextsPanel } from "./texts-panel";

type PanelKey = "fields" | "routing" | "coverage" | "texts" | "pipeline";

const PANEL_ORDER: PanelKey[] = ["fields", "routing", "coverage", "texts", "pipeline"];

export interface Selection {
  fieldId: number;
  docId: string;
  /** bumps on every click so the viewer scrolls again even for the same field */
  nonce: number;
}

/** Neighbours of the claim in its queue tab, in the queue page's order (oldest first). */
function queueNav(claim: ClaimDetail | undefined, list: ClaimRow[] | undefined): QueueNav | undefined {
  if (!claim?.queue || !list) return undefined;
  const rows = list.filter((r) => r.queue === claim.queue && r.status === "IN_REVIEW").sort((a, b) => b.age_hours - a.age_hours);
  const i = rows.findIndex((r) => r.id === claim.id);
  if (i < 0) return undefined;
  const link = (r: ClaimRow | undefined) => (r ? { href: `/claims/${r.id}`, label: r.reference } : undefined);
  return { prev: link(rows[i - 1]), next: link(rows[i + 1]), position: `${i + 1} of ${rows.length} in ${queueEntry(claim.queue)?.label ?? "the queue"}` };
}

export function ClaimView({ id }: { id: string }) {
  const notify = useToast();
  // Poll while the pipeline still owns the claim; stop once it reaches review or a final state.
  const { data: claim, error, loading, reload, mutate } = useFetch<ClaimDetail>(`claim:${id}`, () => api.claim(id), {
    pollMs: 10000,
    pollWhile: (c) => !c || PIPELINE_STATUSES.includes(c.status),
  });
  const [panel, setPanel] = useState<PanelKey>("fields");
  const [activeDoc, setActiveDoc] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  // The queue the claim sits in, in the queue page's order (oldest first), for ‹ › and "Approve and open next".
  const { data: list } = useFetch("claims:nav", () => api.claims());
  const nav = queueNav(claim, list);
  // The new panel slides in from the side of the tab the handler moved to.
  const swap = useSwapDirection(PANEL_ORDER.indexOf(panel));

  const running = claim ? PIPELINE_STATUSES.includes(claim.status) : false;

  const docId = activeDoc ?? claim?.documents[0]?.id ?? null;

  const selectedField = useMemo<Field | null>(() => {
    if (!claim || !selection) return null;
    for (const d of claim.documents) for (const f of d.fields) if (f.id === selection.fieldId) return f;
    return null;
  }, [claim, selection]);

  function select(field: Field, documentId: string) {
    setActiveDoc(documentId);
    setSelection((s) => ({ fieldId: field.id, docId: documentId, nonce: (s?.nonce ?? 0) + 1 }));
  }

  function selectFromViewer(field: Field, documentId: string) {
    select(field, documentId);
    setPanel("fields");
  }

  function onFieldSaved(result: FieldPatchResult) {
    mutate((c) => ({
      ...c,
      version: result.claim_version,
      needs_reassessment: true, // routing, payout and letters were computed from the old value
      documents: c.documents.map((d) => ({
        ...d,
        fields: d.fields.map((f) =>
          f.id === result.id
            ? { ...f, value: result.value, value_norm: result.value_norm, corrected: true, grounded: true, confidence: 1 }
            : f,
        ),
      })),
    }));
    notify("success", "Field corrected", "Saved and logged. Reassess before approving.");
  }

  if (loading) {
    return (
      <div className="cp-text-cell flex h-full items-center justify-center gap-8 text-ink-subtle" role="status">
        <Spinner /> Loading claim
      </div>
    );
  }

  if (!claim) {
    const notFound = error === "no such claim";
    return (
      <div className="mx-auto max-w-[35rem] px-32 py-64">
        {notFound ? (
          <EmptyState
            icon="file-unknown"
            title="Claim not found."
            description={`No claim has the ID ${id}.`}
            action={<InlineLink href="/">Back to the queue</InlineLink>}
          />
        ) : (
          <Alert tone="danger" action={{ label: "Retry", onClick: reload }}>
            {error ?? "The claim could not be loaded."}
          </Alert>
        )}
      </div>
    );
  }

  const fieldCount = claim.documents.reduce((n, d) => n + d.fields.length, 0);
  const flagged = claim.documents.reduce((n, d) => n + d.fields.filter(isFlagged).length, 0);
  const violations = claim.summaries.some((s) => s.fact_violations.length > 0);
  const stepErrors = claim.steps.some((s) => s.status !== "ok");
  const notCovered = claim.coverage.some((c) => c.verdict !== "covered");

  const tabs: TabItem<PanelKey>[] = [
    {
      key: "fields",
      label: "Fields",
      count: fieldCount,
      flag: flagged ? "warning" : undefined,
      title: flagged ? `${flagged} fields to check` : undefined,
    },
    {
      key: "routing",
      label: "Routing",
      count: claim.routing ? claim.routing.rule_hits.length : undefined,
      flag: injectionHits(claim).length ? "danger" : undefined,
      title: injectionHits(claim).length ? "A document addresses the AI system" : undefined,
    },
    {
      key: "coverage",
      label: "Coverage",
      count: claim.coverage.length || undefined,
      flag: notCovered ? "warning" : undefined,
    },
    { key: "texts", label: "Texts", count: claim.summaries.length || undefined, flag: violations ? "danger" : undefined },
    { key: "pipeline", label: "Pipeline", flag: stepErrors ? "danger" : undefined, title: stepErrors ? "Some steps failed or were retried" : undefined },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ClaimHeader claim={claim} error={error} running={running} onChanged={reload} nav={nav} />
      <InjectionWarning claim={claim} />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.08fr)_minmax(30rem,1fr)]">
        <DocumentViewer
          documents={claim.documents}
          activeDocId={docId}
          onActiveDocChange={setActiveDoc}
          selection={selection}
          selectedField={selectedField}
          onSelectField={selectFromViewer}
        />
        <section className="flex min-h-0 flex-col bg-surface hairline-l">
          <Tabs variant="line" tabs={tabs} value={panel} onValueChange={setPanel} label="Claim details" className="px-20 pt-12" />
          <div
            className="pane-scroll min-h-0 flex-1 overflow-y-auto"
            id="claim-panel-scroll"
            role="tabpanel"
            aria-label={tabs.find((t) => t.key === panel)?.label as string}
          >
            <div key={panel} className={swap}>
            {panel === "fields" ? (
              <FieldPanel
                documents={claim.documents}
                activeDocId={docId}
                selectedFieldId={selection?.fieldId ?? null}
                editable={claim.status === "IN_REVIEW"}
                status={claim.status}
                claimVersion={claim.version}
                onSelect={select}
                onShowDocument={setActiveDoc}
                onSaved={onFieldSaved}
              />
            ) : panel === "routing" ? (
              <RoutingPanel routing={claim.routing} status={claim.status} />
            ) : panel === "coverage" ? (
              <CoveragePanel items={claim.coverage} assessment={claim.assessment} status={claim.status} />
            ) : panel === "texts" ? (
              <TextsPanel summaries={claim.summaries} status={claim.status} />
            ) : (
              <PipelinePanel steps={claim.steps} audit={claim.audit} traceUrl={claim.trace_url} />
            )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
