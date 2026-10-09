"use client";

import { createContext, useContext } from "react";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useFetch } from "@/lib/use-fetch";

const UserContext = createContext<User | null>(null);

export function useUser(): User {
  const user = useContext(UserContext);
  if (!user) throw new Error("useUser needs <AuthGate>");
  return user;
}

/** Loads the session user; a 401 sends the browser to /login (see lib/api.ts). */
export function AuthGate({
  children,
  fallback,
  renderError,
}: {
  children: React.ReactNode;
  fallback: React.ReactNode;
  renderError: (message: string, retry: () => void) => React.ReactNode;
}) {
  const { data, error, reload } = useFetch("me", api.me);
  if (data) return <UserContext.Provider value={data}>{children}</UserContext.Provider>;
  if (error && !error.startsWith("Your session")) return <>{renderError(error, reload)}</>;
  return <>{fallback}</>;
}
