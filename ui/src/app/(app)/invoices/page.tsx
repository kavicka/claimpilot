import type { Metadata } from "next";
import { Suspense } from "react";

import { InvoiceQueue } from "@/components/invoice/invoice-queue";

export const metadata: Metadata = { title: "Invoices" };

export default function InvoicesPage() {
  return (
    <Suspense>
      <InvoiceQueue />
    </Suspense>
  );
}
