"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
export default function WorkflowError({ reset }: { reset: () => void }) {
  return (
    <div
      role="alert"
      className="max-w-xl space-y-5 rounded-xl border bg-card p-6"
    >
      <h1 className="text-xl font-bold">دریافت فرایند انجام نشد</h1>
      <p className="text-sm leading-7 text-muted-foreground">
        ارتباط سرویس یا مجوز فروشگاه را بررسی کنید. دادهٔ این صفحه هنوز بارگذاری
        نشده است.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button onClick={reset}>تلاش دوباره</Button>
        <Button asChild variant="outline">
          <Link href="/studio/workflows">فهرست فرایندها</Link>
        </Button>
      </div>
    </div>
  );
}
