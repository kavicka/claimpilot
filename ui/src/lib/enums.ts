import type { IconName, TagTone } from "@claimpilot/ui";

import { humanize } from "./format";
import type { ClaimStatus } from "./types";

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

export const STATUS: Record<ClaimStatus, EnumEntry> = {
  RECEIVED: { label: "Received", tone: "neutral", icon: "circle-dashed" },
  PARSED: { label: "Parsed", tone: "neutral", icon: "circle-dashed" },
  REDACTED: { label: "Redacted", tone: "neutral", icon: "circle-dashed" },
  EXTRACTED: { label: "Extracted", tone: "neutral", icon: "circle-dashed" },
  ROUTED: { label: "Routed", tone: "neutral", icon: "circle-dashed" },
  ASSESSED: { label: "Assessed", tone: "neutral", icon: "circle-dashed" },
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
