"use client";

import { useTheme } from "next-themes";
import { ThinkingOrb, type OrbState } from "thinking-orbs";
import { cn } from "@/lib/utils";

/** Pair a decorative orb with readable progress; the caller owns operation state. */
export function ActivityIndicator({
  label,
  state = "working",
  onPrimary = false,
  announce = true,
  className,
}: {
  label: string;
  state?: Extract<OrbState, "working" | "connecting" | "searching">;
  onPrimary?: boolean;
  announce?: boolean;
  className?: string;
}) {
  const { resolvedTheme } = useTheme();
  // Primary buttons invert their ink between the dashboard's two palettes.
  const theme = onPrimary ? (resolvedTheme === "dark" ? "light" : "dark") : "auto";
  return (
    <span role={announce ? "status" : undefined} aria-atomic={announce || undefined}
      className={cn("inline-flex min-w-0 max-w-full items-center gap-2", className)}>
      <ThinkingOrb state={state} size={20} theme={theme} gravity={false}
        aria-hidden="true" tabIndex={-1} className="shrink-0" />
      <span className="min-w-0 break-words">{label}</span>
    </span>
  );
}
