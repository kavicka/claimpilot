"use client";

import { Alert, Sidebar as DsSidebar, Skeleton } from "@crm-ui/react";

import { AuthGate } from "@/components/shell/auth";
import { Brand, Sidebar } from "@/components/shell/sidebar";

/** App shell: sidebar left, white main area right. Designed at 1440 px. */
function Frame({ side, children }: { side: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex h-screen min-w-[73.75rem] overflow-hidden bg-surface">
      {side}
      <main className="pane-scroll min-w-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

const bareSide = (
  <DsSidebar className="h-full shrink-0">
    <Brand />
  </DsSidebar>
);

const placeholder = (
  <Frame side={bareSide}>
    <div className="flex flex-col gap-12 px-60 py-42" aria-busy="true">
      <Skeleton width={160} height={24} />
      <Skeleton width={360} height={14} />
    </div>
  </Frame>
);

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate
      fallback={placeholder}
      renderError={(message, retry) => (
        <Frame side={bareSide}>
          <div className="max-w-[35rem] px-60 py-42">
            <Alert tone="danger" action={{ label: "Retry", onClick: retry }}>
              {message}
            </Alert>
          </div>
        </Frame>
      )}
    >
      <Frame side={<Sidebar />}>{children}</Frame>
    </AuthGate>
  );
}
