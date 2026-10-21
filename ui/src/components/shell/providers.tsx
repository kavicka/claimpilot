"use client";

import { LinkProvider, ToastProvider } from "@crm-ui/react";
import Link from "next/link";

/** Design-system links navigate client-side; toasts show bottom right. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <LinkProvider component={Link}>
      <ToastProvider>{children}</ToastProvider>
    </LinkProvider>
  );
}
