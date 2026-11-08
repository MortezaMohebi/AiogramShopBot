import * as React from "react";
import { cn } from "@/lib/utils";

/** RTL-safe accessible text input with visible focus state. */
export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn("flex h-10 min-w-0 w-full rounded-md border border-input bg-background px-3 text-base text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive sm:text-sm", className)} {...props} />;
}
