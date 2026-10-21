"use client";

import { Alert, Button, DataTable, EmptyState, Icon, IconButton, Tag, useToast, type Column } from "@claimpilot/ui";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { DataPage } from "@/components/shell/page";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PIPELINE_STATUSES, QUEUE, categoryEntry, statusEntry } from "@/lib/enums";
import { when } from "@/lib/format";
import type { ClaimStatus, QueueName } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

// The same limits the api enforces (services/api/src/claimpilot_api/main.py), checked here so a
// handler hears about a bad file before anything is sent.
const ALLOWED = [".pdf", ".jpg", ".jpeg", ".png"];
const HINTS: Record<string, string> = {
  ".heic": "HEIC photos from an iPhone are not accepted; export them as JPG",
  ".heif": "HEIF photos are not accepted; export them as JPG",
  ".docx": "Word files are not accepted; save them as PDF",
};
const MAX_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 20;
const STORE = "claimpilot.uploads";

interface Upload {
  id: string;
  reference: string;
  documents: number;
  at: string;
}

interface Row extends Upload {
  status: ClaimStatus;
  queue: QueueName | null;
}

function suffixOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

export function problemOf(file: File): string | null {
  const suffix = suffixOf(file.name);
  if (!ALLOWED.includes(suffix)) return `${file.name}: ${HINTS[suffix] ?? "only PDF, JPG and PNG are accepted"}`;
  if (file.size > MAX_BYTES) return `${file.name}: larger than 20 MB`;
  if (file.size === 0) return `${file.name}: the file is empty`;
  return null;
}

function bytes(n: number): string {
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

// Uploads made in this browser tab, so the list survives moving to another page and back.
function loadUploads(): Upload[] {
  try {
    const raw = window.sessionStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Upload[]) : [];
  } catch {
    return [];
  }
}

function saveUploads(uploads: Upload[]) {
  try {
    window.sessionStorage.setItem(STORE, JSON.stringify(uploads));
  } catch {
    // Storage off or full: the list still works until the page is left.
  }
}

const COLUMNS: Column<Row>[] = [
  { key: "reference", header: "Reference", icon: "hash", width: 160, value: (r) => r.reference },
  { key: "documents", header: "Documents", kind: "number", width: 112, value: (r) => r.documents },
  {
    key: "status",
    header: "Status",
    icon: "circle-dashed",
    width: 140,
    value: (r) => statusEntry(r.status).label,
    render: (r) => {
      const s = statusEntry(r.status);
      return (
        <Tag tone={s.tone} icon={s.icon ?? null} size="md">
          {s.label}
        </Tag>
      );
    },
  },
  {
    key: "queue",
    header: "Queue",
    icon: "inbox",
    width: 140,
    value: (r) => r.queue,
    render: (r) => {
      const q = categoryEntry(QUEUE, r.queue);
      return q ? (
        <Tag tone={q.tone} dot size="md">
          {q.label}
        </Tag>
      ) : (
        <span className="text-ink-subtle">–</span>
      );
    },
  },
  { key: "at", header: "Uploaded", icon: "clock", value: (r) => when(r.at) },
];

export function UploadView() {
  const router = useRouter();
  const notify = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  // The (app) layout renders only after the session check, never on the server, so storage is there.
  const [uploads, setUploads] = useState<Upload[]>(loadUploads);

  // Follow the uploaded claims through the pipeline until each one reaches review or fails.
  const claims = useFetch(uploads.length ? "claims" : null, () => api.claims(), {
    pollMs: 3000,
    pollWhile: (rows) => uploads.some((u) => PIPELINE_STATUSES.includes(rows?.find((c) => c.id === u.id)?.status ?? "RECEIVED")),
  });

  const rows: Row[] = uploads.map((u) => {
    const claim = claims.data?.find((c) => c.id === u.id);
    return { ...u, status: claim?.status ?? "RECEIVED", queue: claim?.queue ?? null };
  });

  function add(picked: FileList | null) {
    if (!picked) return;
    const found: string[] = [];
    const next = [...files];
    for (const file of Array.from(picked)) {
      const problem = problemOf(file);
      if (problem) found.push(problem);
      else if (next.length >= MAX_FILES) found.push(`${file.name}: a claim takes at most ${MAX_FILES} documents`);
      else if (!next.some((f) => sameFile(f, file))) next.push(file);
    }
    setFiles(next);
    setProblems(found);
    setError(null);
  }

  async function send() {
    setSending(true);
    setError(null);
    try {
      const claim = await api.upload(files);
      const next = [{ id: claim.id, reference: claim.reference, documents: claim.documents, at: new Date().toISOString() }, ...uploads];
      setUploads(next);
      saveUploads(next);
      setFiles([]);
      setProblems([]);
      claims.reload();
      notify("success", `${claim.reference} created`, `${claim.documents} ${claim.documents === 1 ? "document" : "documents"} sent to the pipeline.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  const total = files.reduce((sum, f) => sum + f.size, 0);

  return (
    <DataPage
      crumbs={[{ label: "Claims", href: "/" }, { label: "Upload" }]}
      title="Upload"
      subtitle="Upload the documents of one claim. The pipeline reads them and puts the claim in a review queue."
    >
      <section
        aria-label="Documents to upload"
        className={cn(
          "flex flex-col items-center gap-12 rounded-(--radius-12) border border-dashed px-24 py-40 text-center transition-colors",
          dragging ? "border-accent bg-accent-soft" : "border-line-control bg-surface-subtle",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          add(e.dataTransfer.files);
        }}
      >
        <span className="cp-list-item__tile">
          <Icon name="file-text" size={16} />
        </span>
        <p className="cp-text-body-strong text-ink">Drop files here</p>
        <p className="cp-text-meta text-ink-subtle">
          PDF, JPG or PNG, up to {MAX_FILES} files and 20 MB each. All files become one claim.
        </p>
        <Button icon="plus" onClick={() => input.current?.click()} disabled={sending}>
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = ""; // choosing the same file again fires change again
          }}
        />
      </section>

      {problems.length > 0 ? (
        <Alert tone="warning" action={{ label: "Dismiss", onClick: () => setProblems([]) }}>
          {problems.length === 1 ? "Not added: " : `${problems.length} files not added: `}
          {problems.join("; ")}.
        </Alert>
      ) : null}

      {files.length > 0 ? (
        <section aria-label="Selected files" className="flex flex-col rounded-(--radius-12) bg-surface hairline">
          <ul className="flex flex-col">
            {files.map((file, i) => (
              <li
                key={`${file.name}-${file.size}-${file.lastModified}`}
                className={cn("flex items-center gap-8 px-16 py-8", i > 0 && "hairline-t")}
              >
                <Icon name={suffixOf(file.name) === ".pdf" ? "file-text" : "image-off"} size={16} className="text-ink-subtle" />
                <span className="cp-text-cell min-w-0 flex-1 truncate text-ink">{file.name}</span>
                <span className="cp-text-meta tnum text-ink-subtle">{bytes(file.size)}</span>
                <IconButton
                  variant="bare"
                  icon="close"
                  label={`Remove ${file.name}`}
                  disabled={sending}
                  onClick={() => setFiles(files.filter((f) => f !== file))}
                />
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-8 px-16 py-12 hairline-t">
            <p className="cp-text-meta tnum flex-1 text-ink-subtle">
              {files.length} {files.length === 1 ? "file" : "files"} · {bytes(total)}
            </p>
            <Button variant="ghost" onClick={() => setFiles([])} disabled={sending}>
              Clear
            </Button>
            <Button variant="primary" icon="sent-02" onClick={send} loading={sending}>
              Upload {files.length === 1 ? "1 file" : `${files.length} files`}
            </Button>
          </div>
        </section>
      ) : null}

      {error ? <Alert tone="danger">{error}</Alert> : null}

      <h2 className="cp-text-panel-title mt-20 text-ink">Uploaded in this session</h2>
      {claims.error ? (
        <Alert tone="danger" action={{ label: "Retry", onClick: claims.reload }}>
          {claims.error}
        </Alert>
      ) : null}
      <DataTable
        label="Uploaded claims"
        columns={COLUMNS}
        rows={rows}
        rowKey={(r) => r.id}
        onRowClick={(r) => router.push(`/claims/${r.id}`)}
        empty={<EmptyState icon="inbox" title="No claims uploaded yet." description="Claims you upload here appear in this list with their pipeline status." />}
      />
    </DataPage>
  );
}
