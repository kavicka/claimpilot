import { forwardRef } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "approve" | "outline" | "danger" | "ghost";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-neutral-800 shadow-sm",
  approve: "bg-emerald-700 text-white hover:bg-emerald-800 shadow-sm",
  outline: "border border-line-2 bg-sheet text-ink hover:bg-stone-50",
  danger: "border border-red-200 bg-sheet text-red-700 hover:bg-red-50",
  ghost: "text-ink-2 hover:bg-black/5 hover:text-ink",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-2.5 text-[13px] gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
};

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }
>(function Button({ variant = "outline", size = "md", className, type = "button", ...props }, ref) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    />
  );
});
