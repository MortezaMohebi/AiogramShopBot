import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A normal link keeps keyboard, screen reader and open-in-new-tab behavior. */
export function RecordLink({ href, children, className }: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return <Link href={href} prefetch={false} data-record-link
    className={cn("rounded-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", className)}
  >{children}</Link>;
}
