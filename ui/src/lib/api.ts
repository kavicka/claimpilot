// Tiny typed client. Every call goes to this origin; next.config.ts rewrites /api to the API host.

import type {
  ActionResult,
  ClaimAction,
  ClaimDetail,
  ClaimRow,
  Clause,
  EvalReport,
  FieldPatchResult,
  InvoiceActionResult,
  InvoiceDetail,
  InvoiceRow,
  Ops,
  UploadedClaim,
  UploadedInvoice,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{loc, msg, type}]
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
  }
  return `Request failed (HTTP ${status})`;
}

export function loginPath(): string {
  if (typeof window === "undefined") return "/login";
  const here = window.location.pathname + window.location.search;
  return here === "/" ? "/login" : `/login?next=${encodeURIComponent(here)}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // FormData sets its own multipart content type with the boundary.
  const form = body instanceof FormData;
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: body === undefined || form ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.assign(loginPath());
    }
    throw new ApiError(401, "Your session has ended. Log in again.");
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(parsed, res.status));
  return parsed as T;
}

function query(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  login: (username: string, password: string) =>
    request<User>("POST", "/api/auth/login", { username, password }),
  logout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  me: () => request<User>("GET", "/api/auth/me"),

  // One claim from all the files; the api stores them and enqueues the pipeline.
  upload: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return request<UploadedClaim>("POST", "/api/claims", form);
  },
  claims: (params: { queue?: string; status?: string } = {}) =>
    request<ClaimRow[]>("GET", `/api/review/claims${query(params)}`),
  claim: (id: string) => request<ClaimDetail>("GET", `/api/review/claims/${encodeURIComponent(id)}`),
  clause: (clauseId: string) =>
    request<Clause>("GET", `/api/review/clauses/${encodeURIComponent(clauseId)}`),
  // `version` is the claim version the page showed; the api refuses with 409 if it changed since.
  patchField: (fieldId: number, value: string, version: number) =>
    request<FieldPatchResult>("PATCH", `/api/review/fields/${fieldId}`, { value, version }),
  act: (claimId: string, action: ClaimAction, version: number, note?: string) =>
    request<ActionResult>(
      "POST",
      `/api/review/claims/${encodeURIComponent(claimId)}/actions/${action}`,
      { note: note?.trim() ? note.trim() : null, version },
    ),

  // One supplier document per invoice.
  uploadInvoice: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<UploadedInvoice>("POST", "/api/invoices", form);
  },
  invoices: (params: { queue?: string; status?: string } = {}) =>
    request<InvoiceRow[]>("GET", `/api/review/invoices${query(params)}`),
  invoice: (id: string) => request<InvoiceDetail>("GET", `/api/review/invoices/${encodeURIComponent(id)}`),
  actInvoice: (invoiceId: string, action: ClaimAction, version: number, note?: string) =>
    request<InvoiceActionResult>(
      "POST",
      `/api/review/invoices/${encodeURIComponent(invoiceId)}/actions/${action}`,
      { note: note?.trim() ? note.trim() : null, version },
    ),

  ops: () => request<Ops>("GET", "/api/review/ops"),
  evals: () => request<EvalReport[]>("GET", "/api/review/evals"),
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError) return "The API did not answer. Is it running on port 4400?";
  if (err instanceof Error) return err.message;
  return "Unexpected error.";
}
