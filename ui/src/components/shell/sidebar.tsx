"use client";

import { Activity, FlaskConical, Inbox, LogOut } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { ROLE } from "@/lib/enums";
import { initials } from "@/lib/format";

import { useUser } from "./auth";

const NAV: { label: string; href: string; icon: LucideIcon; match: (p: string) => boolean }[] = [
  { label: "Queue", href: "/", icon: Inbox, match: (p) => p === "/" || p.startsWith("/claims") },
  { label: "Ops", href: "/ops", icon: Activity, match: (p) => p.startsWith("/ops") },
  { label: "Evals", href: "/evals", icon: FlaskConical, match: (p) => p.startsWith("/evals") },
];

export function Brand({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative flex size-8 items-center justify-center overflow-hidden rounded-[9px] bg-ink font-mono text-[12px] font-medium tracking-tight text-white">
        CP
        <span aria-hidden className="absolute bottom-[5px] left-[7px] h-[3px] w-[18px] rounded-full bg-marker" />
      </div>
      <div className="leading-tight">
        <p className="text-[15px] font-semibold tracking-tight">ClaimPilot</p>
        <p className="text-[11px] text-ink-3">Claims review</p>
      </div>
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useUser();
  const [leaving, setLeaving] = useState(false);

  async function logout() {
    setLeaving(true);
    try {
      await api.logout();
    } finally {
      router.replace("/login");
    }
  }

  return (
    <aside className="flex h-full w-[220px] shrink-0 flex-col px-3 py-4">
      <Brand className="px-2 pb-6" />
      <nav aria-label="Main" className="flex flex-col gap-0.5">
        {NAV.map(({ label, href, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition",
                active ? "bg-sheet text-ink shadow-sm ring-1 ring-black/5" : "text-ink-2 hover:bg-black/[0.04] hover:text-ink",
              )}
            >
              <Icon className={cn("size-[18px]", active ? "text-ink" : "text-ink-3 group-hover:text-ink-2")} aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex items-center gap-2.5 rounded-xl px-2 py-2">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-stone-300/70 text-[11px] font-semibold text-ink">
          {initials(user.name)}
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-[13px] font-medium">{user.name}</p>
          <p className="truncate text-[11px] text-ink-3">{ROLE[user.role] ?? user.role}</p>
        </div>
        <Tooltip content="Log out" side="right">
          <button
            type="button"
            onClick={logout}
            disabled={leaving}
            aria-label="Log out"
            className="rounded-md p-1.5 text-ink-3 transition hover:bg-black/5 hover:text-ink disabled:opacity-50"
          >
            <LogOut className="size-4" />
          </button>
        </Tooltip>
      </div>
    </aside>
  );
}
