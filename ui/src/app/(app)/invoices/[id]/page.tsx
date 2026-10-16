import type { Metadata } from "next";

import { InvoiceView } from "@/components/invoice/invoice-view";

export const metadata: Metadata = { title: "Invoice" };

export default async function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvoiceView id={id} />;
}
