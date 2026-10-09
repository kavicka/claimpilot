import type { Metadata } from "next";

import { ClaimView } from "@/components/claim/claim-view";

export const metadata: Metadata = { title: "Claim" };

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ClaimView id={id} />;
}
