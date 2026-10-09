"use client";

import { AuthGate } from "@/components/shell/auth";
import { Brand, Sidebar } from "@/components/shell/sidebar";
import { ErrorNote } from "@/components/ui/empty-state";

function Frame({ side, children }: { side: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex h-screen min-w-[1180px] overflow-hidden bg-desk">
      {side}
      <main className="pane-scroll min-w-0 flex-1 overflow-y-auto rounded-tl-2xl border-l border-t border-line bg-[#faf9f6]">
        {children}
      </main>
    </div>
  );
}

const placeholder = (
  <Frame
    side={
      <aside className="w-[220px] shrink-0 px-3 py-4">
        <Brand className="px-2" />
      </aside>
    }
  >
    <div className="p-8">
      <div className="h-6 w-40 animate-pulse rounded-md bg-stone-200/70" />
    </div>
  </Frame>
);

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate
      fallback={placeholder}
      renderError={(message, retry) => (
        <Frame
          side={
            <aside className="w-[220px] shrink-0 px-3 py-4">
              <Brand className="px-2" />
            </aside>
          }
        >
          <div className="max-w-xl p-8">
            <ErrorNote message={message} onRetry={retry} />
          </div>
        </Frame>
      )}
    >
      <Frame side={<Sidebar />}>{children}</Frame>
    </AuthGate>
  );
}
