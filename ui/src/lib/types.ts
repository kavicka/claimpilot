// Handwritten mirror of the review API JSON (services/api/src/claimpilot_api/review.py).
// Amounts are decimal strings in EUR unless a currency says otherwise.

export type ClaimStatus =
  | "RECEIVED"
  | "PARSED"
  | "REDACTED"
  | "EXTRACTED"
  | "ROUTED"
  | "ASSESSED"
  | "IN_REVIEW"
  | "APPROVED"
  | "SUBMITTED"
  | "REJECTED"
  | "NEEDS_INFO"
  | "FAILED";

export type QueueName = "fast_track" | "standard" | "senior" | "fraud_review";

export type Role = "handler" | "senior";

export interface User {
  username: string;
  name: string;
  role: Role | string;
}

export interface ClaimRow {
  id: string;
  reference: string;
  status: ClaimStatus;
  queue: QueueName | null;
  claim_type: string | null;
  product: string | null;
  insured: string | null;
  claimed_total_eur: string | null;
  payout_eur: string | null;
  straight_through: boolean;
  age_hours: number;
  error: string | null;
}

/** What POST /api/claims answers (services/api/src/claimpilot_api/main.py, ClaimOut). */
export interface UploadedClaim {
  id: string;
  reference: string;
  status: ClaimStatus;
  queue: QueueName | null;
  claim_type: string | null;
  scenario_id: string | null;
  documents: number;
}

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Field {
  id: number;
  field: string;
  value: string | null;
  value_norm: string | null;
  quote: string | null;
  page: number | null;
  bbox: BBox | null;
  grounded: boolean;
  confidence: number | null;
  checks: Record<string, boolean>;
  corrected: boolean;
}

/** Text a reader of the document cannot see; it never reached a model. */
export interface HiddenText {
  page: number;
  bbox: BBox;
  reason: "low_contrast" | "tiny" | "off_page" | "invisible" | "transparent" | "covered";
  text: string | null;
}

export interface ClaimDocument {
  id: string;
  filename: string;
  doc_type: string | null;
  language: string | null;
  pages: string[];
  fields: Field[];
  hidden_text?: HiddenText[];
}

export interface RuleHit {
  rule: string;
  detail: string;
}

export interface Routing {
  queue: string;
  rule_hits: RuleHit[];
  llm_used: boolean;
  rationale: string | null;
}

export type Verdict = "covered" | "not_covered" | "needs_review";

export interface CoverageItem {
  ref: string;
  description: string | null;
  coverage: string;
  verdict: Verdict;
  clauses: string[];
  claimed: string | null; // null: the amount or its currency could not be read
  currency: string | null;
  payout_eur: string;
  rationale: string | null;
}

export interface Assessment {
  total_payout_eur: string | null;
  deductible_eur: string | null;
  held_eur: string | null;
  by_coverage: Record<string, string>;
  explanation: string[];
}

export type SummaryKind = "handler" | "client_letter" | "group" | "info_request";

export interface FactViolation {
  kind: string;
  text: string;
}

export interface Summary {
  kind: SummaryKind;
  language: string;
  text: string | null;
  fact_violations: FactViolation[];
}

export interface StepRun {
  step: string;
  status: string;
  attempt: number;
  latency_ms: number | null;
  tokens: number;
  models: string[];
  error: string | null;
}

export interface AuditEntry {
  action: string;
  details: Record<string, unknown> | null;
  at: string;
}

export interface ClaimFacts {
  claim_type?: string | null;
  claimed_total_eur?: string | null;
  event_date?: string | null;
  min_critical_confidence?: number | null;
  critical_grounded?: boolean | null;
  policy?: Record<string, unknown> | null;
}

export interface ClaimDetail {
  id: string;
  reference: string;
  status: ClaimStatus;
  queue: QueueName | null;
  claim_type: string | null;
  product: string | null;
  policy_number: string | null;
  error: string | null;
  core_claim_id: string | null;
  insured: string | null;
  facts: ClaimFacts | null;
  assessment: Assessment | null;
  needs_reassessment: boolean;
  version: number;
  documents: ClaimDocument[];
  routing: Routing | null;
  coverage: CoverageItem[];
  summaries: Summary[];
  steps: StepRun[];
  trace_url: string | null;
  audit: AuditEntry[];
}

export interface Clause {
  clause_id: string;
  display: string;
  heading: string;
  text: string;
}

export interface FieldPatchResult {
  id: number;
  value: string | null;
  value_norm: string | null;
  claim_version: number;
}

export type ClaimAction = "approve" | "reject" | "request-info" | "escalate" | "reassess" | "retry";

export interface ActionResult {
  status: ClaimStatus;
  queue: QueueName | null;
  version: number;
}

export interface Ops {
  claims: number;
  by_queue: Record<string, number>;
  by_status: Record<string, number>;
  straight_through_rate: number | null;
  latency_p50_s: number | null;
  latency_p95_s: number | null;
  tokens_per_claim: number | null;
  dead_letter: { id: string; reference: string; error: string | null }[];
}

export interface Metric {
  value: number;
  num: number;
  den: number;
}

export interface EvalReport {
  suite: string;
  created: string | null;
  metrics: Record<string, Metric>;
  ops: Record<string, unknown>;
  models: string[] | null;
  notes: string[];
}

// ---- Supplier invoices (services/api/src/claimpilot_api/invoices.py) ----

export type InvoiceStatus =
  | "RECEIVED"
  | "PARSED"
  | "REDACTED"
  | "EXTRACTED"
  | "VALIDATED"
  | "MATCHED"
  | "ROUTED"
  | "IN_REVIEW"
  | "APPROVED"
  | "EXPORTED"
  | "REJECTED"
  | "NEEDS_INFO"
  | "FAILED";

export type InvoiceKind = "invoice" | "credit_note" | "proforma";

export interface InvoiceRow {
  id: string;
  reference: string;
  status: InvoiceStatus;
  queue: QueueName | null;
  kind: InvoiceKind | null;
  supplier: string | null;
  invoice_number: string | null;
  total: string | null;
  currency: string | null;
  /** Failed validation checks plus matching findings. */
  findings: number;
  /** The most serious routing rule that fired. */
  rule: string | null;
  age_hours: number;
  error: string | null;
}

/** What POST /api/invoices answers. */
export interface UploadedInvoice {
  id: string;
  reference: string;
  status: InvoiceStatus;
}

export interface InvoiceDocument {
  id: string;
  filename: string;
  pages: string[];
  hidden_text: HiddenText[];
}

export interface InvoiceLine {
  /** 1-based line number; validation names this line's fields lines[n].<field>. */
  n: number;
  /** The item row's box on the page, when the table was read from word positions. */
  row: { page: number; bbox: BBox } | null;
  fields: Record<string, Field>;
}

export interface ValidationCheck {
  name: string;
  ok: boolean;
  fields: string[];
  detail: string;
}

export interface MatchFinding {
  kind: string;
  /** 0-based index into the lines array; null for the whole invoice. */
  line: number | null;
  detail?: string | null;
}

export interface Matching {
  supplier: string | null;
  order: string | null;
  findings: MatchFinding[];
  lines: { line: number; order_line: number | null }[];
}

export interface InvoiceStep {
  step: string;
  status: string;
  latency_ms: number | null;
  models: string[];
  error: string | null;
  attempt?: number;
  tokens?: number;
}

export interface InvoiceDetail {
  id: string;
  reference: string;
  status: InvoiceStatus;
  queue: QueueName | null;
  kind: InvoiceKind | null;
  invoice_number: string | null;
  total: string | null;
  currency: string | null;
  error: string | null;
  version: number;
  needs_revalidation: boolean;
  /** Set once the ERP accepted the exported UBL. */
  erp_id?: string | null;
  export?: InvoiceExport | null;
  document: InvoiceDocument | null;
  header: Field[];
  lines: InvoiceLine[];
  validation: ValidationCheck[];
  matching: Matching | null;
  routing: RuleHit[];
  steps: InvoiceStep[];
  audit: AuditEntry[];
}

export interface ExportError {
  rule: string;
  field?: string | null;
  message: string;
}

/** The last Peppol UBL export to the ERP: accepted (erp_id), refused (errors) or skipped (note). */
export interface InvoiceExport {
  erp_id?: string | null;
  errors?: ExportError[];
  note?: string | null;
}

export interface InvoiceActionResult {
  status: InvoiceStatus;
  queue: QueueName | null;
  version: number;
}
