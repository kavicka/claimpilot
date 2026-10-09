import type { Metadata } from "next";

import { OpsView } from "@/components/ops/ops-view";

export const metadata: Metadata = { title: "Ops" };

export default function OpsPage() {
  return <OpsView />;
}
