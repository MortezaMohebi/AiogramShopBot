"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
/** Refresh the authoritative server projection without replaying a mutation. */
export function RuntimeRefresh() {
  const router = useRouter(),
    [pending, startTransition] = useTransition();
  return <Button type="button" variant="outline" disabled={pending} onClick={() => startTransition(() => router.refresh())}>
  {pending ? "در حال دریافت…" : "دریافت وضعیت تازه"}
</Button>;
}
