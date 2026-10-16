"use client";

import { IconButton, NavItem, NavList, Sidebar as DsSidebar, SidebarBrand, SidebarUser, Tooltip, type IconName } from "@claimpilot/ui";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";
import { ROLE } from "@/lib/enums";

import { useUser } from "./auth";

const NAV: { label: string; href: string; icon: IconName; match: (p: string) => boolean }[] = [
  { label: "Queue", href: "/", icon: "inbox", match: (p) => p === "/" || p.startsWith("/claims") },
  { label: "Ops", href: "/ops", icon: "activity", match: (p) => p.startsWith("/ops") },
  { label: "Evals", href: "/evals", icon: "flask", match: (p) => p.startsWith("/evals") },
];

/** Product mark and name. */
export function Brand() {
  return (
    <SidebarBrand
      logo={<img src="/brand/claimpilot.svg" alt="" width={24} height={24} />}
      name="ClaimPilot"
      detail="Claims review"
    />
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
    <DsSidebar
      className="h-full shrink-0"
      footer={
        <SidebarUser
          name={user.name}
          detail={ROLE[user.role] ?? user.role}
          action={
            <Tooltip content="Log out" side="right">
              <IconButton variant="bare" icon="logout" label="Log out" onClick={logout} disabled={leaving} />
            </Tooltip>
          }
        />
      }
    >
      <Brand />
      <NavList>
        {NAV.map(({ label, href, icon, match }) => (
          <NavItem key={href} href={href} icon={icon} active={match(pathname)}>
            {label}
          </NavItem>
        ))}
      </NavList>
    </DsSidebar>
  );
}
