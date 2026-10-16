import type { IconName, TagTone } from "@claimpilot/ui";

import { humanize } from "./format";
import type { ClaimStatus, InvoiceStatus } from "./types";

export interface EnumEntry {
  label: string;
  tone: TagTone;
  icon?: IconName;
}

export const PIPELINE_STATUSES: ClaimStatus[] = [
  "RECEIVED",
  "PARSED",
  "REDACTED",
  "EXTRACTED",
  "ROUTED",
  "ASSESSED",
];

export const DECIDED_STATUSES: ClaimStatus[] = ["APPROVED", "SUBMITTED", "REJECTED"];

export const STATUS_ORDER: ClaimStatus[] = [
  ...PIPELINE_STATUSES,
  "IN_REVIEW",
  "NEEDS_INFO",
  "APPROVED",
  "SUBMITTED",
  "REJECTED",
  "FAILED",
];

export const STATUS: Record<ClaimStatus | InvoiceStatus, EnumEntry> = {
  RECEIVED: { label: "Received", tone: "neutral", icon: "circle-dashed" },
  PARSED: { label: "Parsed", tone: "neutral", icon: "circle-dashed" },
  REDACTED: { label: "Redacted", tone: "neutral", icon: "circle-dashed" },
  EXTRACTED: { label: "Extracted", tone: "neutral", icon: "circle-dashed" },
  ROUTED: { label: "Routed", tone: "neutral", icon: "circle-dashed" },
  ASSESSED: { label: "Assessed", tone: "neutral", icon: "circle-dashed" },
  VALIDATED: { label: "Validated", tone: "neutral", icon: "circle-dashed" },
  MATCHED: { label: "Matched", tone: "neutral", icon: "circle-dashed" },
  EXPORTED: { label: "Exported", tone: "success", icon: "sent-02" },
  IN_REVIEW: { label: "In review", tone: "info", icon: "eye" },
  APPROVED: { label: "Approved", tone: "success", icon: "check" },
  SUBMITTED: { label: "Submitted", tone: "success", icon: "sent-02" },
  REJECTED: { label: "Rejected", tone: "danger", icon: "ban" },
  NEEDS_INFO: { label: "Needs info", tone: "warning", icon: "help-circle" },
  FAILED: { label: "Failed", tone: "danger", icon: "alert-circle" },
};

export function statusEntry(status: string): EnumEntry {
  return STATUS[status as ClaimStatus] ?? { label: humanize(status), tone: "neutral" };
}

export const QUEUES = ["fast_track", "standard", "senior", "fraud_review"] as const;

export const QUEUE: Record<string, EnumEntry> = {
  fast_track: { label: "Fast track", tone: "success" },
  standard: { label: "Standard", tone: "info" },
  senior: { label: "Senior", tone: "purple" },
  fraud_review: { label: "Fraud review", tone: "danger" },
  needs_info: { label: "Needs info", tone: "warning" },
};

export function queueEntry(queue: string | null): EnumEntry | null {
  if (!queue || queue === "none") return null;
  return QUEUE[queue] ?? { label: humanize(queue), tone: "neutral" };
}

export const CLAIM_TYPE: Record<string, EnumEntry> = {
  medical: { label: "Medical", tone: "info" },
  luggage: { label: "Luggage", tone: "orange" },
  cancellation: { label: "Cancellation", tone: "purple" },
  accident: { label: "Accident", tone: "danger" },
};

export const COVERAGE: Record<string, EnumEntry> = {
  medical: { label: "Medical", tone: "info" },
  luggage: { label: "Luggage", tone: "orange" },
  delay: { label: "Delay", tone: "neutral" },
  cancellation: { label: "Cancellation", tone: "purple" },
  accident: { label: "Accident", tone: "danger" },
  liability: { label: "Liability", tone: "warning" },
};

export function categoryEntry(map: Record<string, EnumEntry>, value: string | null): EnumEntry | null {
  if (!value) return null;
  return map[value] ?? { label: humanize(value), tone: "neutral" };
}

export const VERDICT: Record<string, EnumEntry> = {
  covered: { label: "Covered", tone: "success", icon: "check" },
  not_covered: { label: "Not covered", tone: "danger", icon: "close" },
  needs_review: { label: "Needs review", tone: "warning", icon: "help-circle" },
};

export const DOC_TYPE: Record<string, string> = {
  claim_form: "Claim form",
  policy_certificate: "Policy certificate",
  medical_report: "Medical report",
  medical_invoice: "Medical invoice",
  pharmacy_receipt: "Pharmacy receipt",
  property_irregularity_report: "Property irregularity report",
  police_report: "Police report",
  booking_confirmation: "Booking confirmation",
};

export function docTypeLabel(docType: string | null): string {
  if (!docType) return "Unclassified";
  return DOC_TYPE[docType] ?? humanize(docType);
}

/** Label for a failed check, phrased as the problem. */
export const FAILED_CHECK: Record<string, string> = {
  parses: "Does not parse",
  date_order: "Dates out of order",
  total_matches_lines: "Total ≠ sum of lines",
  event_in_trip: "Event outside trip",
  event_in_policy: "Event outside policy period",
  iban_checksum: "IBAN checksum fails",
  birth_number_valid: "Invalid birth number",
  same_person: "Different person than on the claim form",
  // invoices (services/worker/src/claimpilot_worker/validation/invoice.py)
  line_complete: "Quantity or line total missing",
  line_math: "Quantity × price ≠ line total",
  line_vat: "Line VAT does not match the rate",
  line_gross: "Net + VAT ≠ gross",
  ean: "EAN check digit fails",
  recap_base: "VAT recap base ≠ sum of lines",
  recap_vat: "VAT recap does not add up",
  total_net: "Net total ≠ VAT recap",
  total_vat: "VAT total ≠ VAT recap",
  lines_total: "Lines do not add up to the total",
  total: "Total missing or ≠ net + VAT",
  amount_due: "Amount due does not add up",
  supplier_ico: "Supplier IČO is not valid",
  supplier_vat_id: "Supplier VAT ID is not valid",
  supplier_iban: "Supplier IBAN is not valid",
  buyer_vat_id: "Buyer VAT ID is not valid",
  buyer_is_ours: "Buyer is not our company",
  vat_regime: "VAT regime does not fit the supplier",
  pages_complete: "Pages missing",
  second_currency: "Second-currency total does not match the rate",
  credit_note_original: "Credit note without an original invoice",
  credit_note_sign: "Credit note total is not negative",
  duplicate: "Already received",
};

export function failedCheckLabel(name: string): string {
  return FAILED_CHECK[name] ?? `${humanize(name)} failed`;
}

export const SUMMARY_KIND: Record<string, string> = {
  handler: "Handler summary",
  client_letter: "Client letter",
  group: "Group summary",
  info_request: "Information request",
};

export const ROLE: Record<string, string> = {
  handler: "Handler",
  senior: "Senior handler",
};

// ---- Supplier invoices ----

/** The worker owns the invoice in these states (APPROVED: the ERP export is running). */
export const INVOICE_PIPELINE_STATUSES: InvoiceStatus[] = [
  "RECEIVED",
  "PARSED",
  "REDACTED",
  "EXTRACTED",
  "VALIDATED",
  "MATCHED",
  "ROUTED",
];

export const INVOICE_DECIDED_STATUSES: InvoiceStatus[] = ["APPROVED", "EXPORTED", "REJECTED"];

export const INVOICE_KIND: Record<string, EnumEntry> = {
  invoice: { label: "Invoice", tone: "info" },
  credit_note: { label: "Credit note", tone: "orange" },
  proforma: { label: "Proforma", tone: "purple" },
};

/** ERP matching findings (services/worker/src/claimpilot_worker/matching/invoice.py). */
export const FINDING: Record<string, string> = {
  price_diff: "Price differs from the order",
  short_delivery: "Less received than invoiced",
  over_delivery: "More received than invoiced",
  not_ordered: "Not on the order",
  not_received: "No goods receipt",
  unknown_order: "Order not found in the ERP",
  order_mismatch: "Order belongs to another supplier or buyer",
  unknown_supplier: "Supplier not in the ERP",
  iban_changed: "IBAN not on the supplier's record",
  unknown_original: "Original invoice not found",
};

export function findingLabel(kind: string): string {
  return FINDING[kind] ?? humanize(kind);
}

/** What each invoice routing rule means (services/worker/src/claimpilot_worker/routing/invoice.py). */
export const INVOICE_RULE: Record<string, string> = {
  I1: "IBAN not on the supplier's record",
  I2: "Same supplier and number arrived before",
  I3: "Text addressed to an AI system or hidden from the reader",
  I4: "Supplier not in the ERP",
  I5: "Credit note",
  I6: "Amount above the senior limit",
  I7: "A line differs from the order or the receipt",
  I8: "A validation check failed",
};
