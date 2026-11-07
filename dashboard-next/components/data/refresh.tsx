"use client";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ActivityIndicator } from "@/components/ui/activity-indicator";

/** Re-read server projections; never resubmit a form or replay a mutation. */
export function ReadRefresh() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return <Button type="button" variant="outline" disabled={pending}
    onClick={() => startTransition(() => router.refresh())}>
    {pending ? <ActivityIndicator announce={false} label="در حال دریافت…" /> : "دریافت دوباره"}
  </Button>;
}
