"use client";

import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

/**
 * Guarded dashboard data/error fallback.
 *
 * Do not claim that a generic render failure proves PostgreSQL is down:
 * failure might occur at the Next.js/bridge HMAC/authorization/API layer.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-xl py-16">
      <Card>
        <CardHeader>
          <div className="mb-4 grid size-12 place-items-center rounded-xl bg-amber-500/10 text-amber-700 dark:text-amber-300">
            <AlertTriangle aria-hidden="true" className="size-6" />
          </div>
          <h1 className="text-xl font-bold">داده‌های داشبورد بارگذاری نشدند</h1>
        </CardHeader>
        <CardContent className="space-y-5">
          <p role="alert" className="text-sm leading-7 text-muted-foreground">
            اطلاعات این صفحه دریافت نشد. دوباره بارگذاری کنید. اگر پیش از این تغییری ثبت کرده‌اید، ابتدا آخرین وضعیت آن را بررسی کنید.
          </p>
          {error.digest ? (
            <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">اطلاعات پشتیبانی</summary><p dir="ltr" className="break-all">Error reference: {error.digest}</p></details>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button type="button" onClick={reset}>
              <RotateCcw aria-hidden="true" className="size-4" />
              بارگذاری دوباره
            </Button>
            <Button asChild variant="outline">
              <Link href="/login">ورود دوباره</Link>
            </Button>
          </div>

        </CardContent>
      </Card>
    </div>
  );
}
