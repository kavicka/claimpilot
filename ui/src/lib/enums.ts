import type { LucideIcon } from "lucide-react";
import {
  Ban,
  Check,
  CircleAlert,
  CircleDashed,
  CircleHelp,
  Eye,
  Send,
  X,
} from "lucide-react";

import type { ChipVariant } from "@/components/ui/chip";

import { humanize } from "./format";
import type { ClaimStatus } from "./types";

export interface EnumEntry {
  label: string;
  variant: ChipVariant;
  icon?: LucideIcon;
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
  RECEIVED: { label: "Received", variant: "neutral", icon: CircleDashed },
  PARSED: { label: "Parsed", variant: "neutral", icon: CircleDashed },
  REDACTED: { label: "Redacted", variant: "neutral", icon: CircleDashed },
  EXTRACTED: { label: "Extracted", variant: "neutral", icon: CircleDashed },
  ROUTED: { label: "Routed", variant: "neutral", icon: CircleDashed },
  ASSESSED: { label: "Assessed", variant: "neutral", icon: CircleDashed },
  IN_REVIEW: { label: "In review", variant: "info", icon: Eye },
  APPROVED: { label: "Approved", variant: "success", icon: Check },
  SUBMITTED: { label: "Submitted", variant: "success", icon: Send },
  REJECTED: { label: "Rejected", variant: "danger", icon: Ban },
  NEEDS_INFO: { label: "Needs info", variant: "warning", icon: CircleHelp },
  FAILED: { label: "Failed", variant: "danger", icon: CircleAlert },
};

export function statusEntry(status: string): EnumEntry {
  return STATUS[status as ClaimStatus] ?? { label: humanize(status), variant: "neutral" };
}

export const QUEUES = ["fast_track", "standard", "senior", "fraud_review"] as const;

export const QUEUE: Record<string, EnumEntry> = {
  fast_track: { label: "Fast track", variant: "success" },
  standard: { label: "Standard", variant: "info" },
  senior: { label: "Senior", variant: "purple" },
  fraud_review: { label: "Fraud review", variant: "danger" },
  needs_info: { label: "Needs info", variant: "warning" },
};

export function queueEntry(queue: string | null): EnumEntry | null {
  if (!queue || queue === "none") return null;
  return QUEUE[queue] ?? { label: humanize(queue), variant: "neutral" };
}

export const CLAIM_TYPE: Record<string, EnumEntry> = {
  medical: { label: "Medical", variant: "info" },
  luggage: { label: "Luggage", variant: "orange" },
  cancellation: { label: "Cancellation", variant: "purple" },
  accident: { label: "Accident", variant: "danger" },
};

export const COVERAGE: Record<string, EnumEntry> = {
  medical: { label: "Medical", variant: "info" },
  luggage: { label: "Luggage", variant: "orange" },
  delay: { label: "Delay", variant: "neutral" },
  cancellation: { label: "Cancellation", variant: "purple" },
  accident: { label: "Accident", variant: "danger" },
  liability: { label: "Liability", variant: "warning" },
};

export function categoryEntry(map: Record<string, EnumEntry>, value: string | null): EnumEntry | null {
  if (!value) return null;
  return map[value] ?? { label: humanize(value), variant: "neutral" };
}

export const VERDICT: Record<string, EnumEntry> = {
  covered: { label: "Covered", variant: "success", icon: Check },
  not_covered: { label: "Not covered", variant: "danger", icon: X },
  needs_review: { label: "Needs review", variant: "warning", icon: CircleHelp },
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
