import * as React from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "warning" | "danger";

/** Compact status label for cards and real payment/campaign states. */
export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.ComponentProps<"span"> & { tone?: Tone }) {
  const classes: Record<Tone, string> = {
    neutral: "bg-secondary text-secondary-foreground",
    success: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
    warning: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
    danger: "bg-red-500/12 text-red-700 dark:text-red-300",
  };
  return (
    <span
      className={cn("inline-flex w-fit items-center rounded-full px-2.5 py-1 text-xs font-medium", classes[tone], className)}
      {...props}
    />
  );
}
