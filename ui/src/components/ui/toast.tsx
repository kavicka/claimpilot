"use client";

import { Check, Info, OctagonX, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/cn";

type Variant = "success" | "info" | "warning" | "danger";

interface Toast {
  id: number;
  variant: Variant;
  title: string;
  description?: string;
}

type Notify = (variant: Variant, title: string, description?: string) => void;

const ToastContext = createContext<Notify | null>(null);

const TILE: Record<Variant, { icon: typeof Check; tile: string; color: string }> = {
  success: { icon: Check, tile: "bg-emerald-500", color: "text-white" },
  info: { icon: Info, tile: "bg-white/[0.07]", color: "text-sky-300" },
  warning: { icon: TriangleAlert, tile: "bg-white/[0.07]", color: "text-amber-300" },
  danger: { icon: OctagonX, tile: "bg-white/[0.07]", color: "text-red-400" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback<Notify>(
    (variant, title, description) => {
      const id = nextId.current++;
      setToasts((ts) => [...ts.slice(-3), { id, variant, title, description }]);
      window.setTimeout(() => dismiss(id), variant === "danger" ? 9000 : 5000);
    },
    [dismiss],
  );

  const value = useMemo(() => notify, [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-[380px] flex-col gap-2"
        role="region"
        aria-label="Notifications"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const { icon: Icon, tile, color } = TILE[t.variant];
          return (
            <div
              key={t.id}
              role={t.variant === "danger" ? "alert" : "status"}
              className="pointer-events-auto relative flex animate-toast gap-3 rounded-[18px] border border-white/10 bg-neutral-950 p-3.5 pr-9 text-white shadow-[0_12px_40px_rgb(0_0_0/0.22)]"
            >
              <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-2xl", tile)}>
                <Icon className={cn("size-[18px]", color)} aria-hidden />
              </div>
              <div className="min-w-0 self-center">
                <p className="text-sm font-medium leading-snug">{t.title}</p>
                {t.description ? (
                  <p className="mt-0.5 text-[13px] leading-snug text-white/60">{t.description}</p>
                ) : null}
              </div>
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => dismiss(t.id)}
                className="absolute right-2.5 top-2.5 rounded-md p-0.5 text-white/40 transition hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useNotify(): Notify {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useNotify needs <ToastProvider>");
  return ctx;
}
