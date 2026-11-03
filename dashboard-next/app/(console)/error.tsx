"use client";

import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
          <CardTitle>داده‌های داشبورد بارگذاری نشدند</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <p role="alert" className="text-sm leading-7 text-muted-foreground">
            درخواست به سرویس مدیریتی کامل نشد. این پیام لزوماً به
            معنی قطعی پایگاه داده نیست؛ ارتباط داخلی، نشست مدیریتی
            یا پردازش API نیز ممکن است دچار خطا شده باشد.
            تا تأیید وضعیت، اطلاعات ساختگی نمایش داده نمی‌شوند.
          </p>
          {error.digest ? (
            <p dir="ltr" className="break-all rounded-md bg-muted p-3 text-xs text-muted-foreground">
              Error reference: {error.digest}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button type="button" onClick={reset}>
              <RotateCcw aria-hidden="true" className="size-4" />
              تلاش دوباره
            </Button>
            <Button asChild variant="outline">
              <Link href="/login">ورود دوباره</Link>
            </Button>
          </div>
          <p className="text-xs leading-6 text-muted-foreground">
            مدیر سیستم می‌تواند در Codespaces با دستور
            <code dir="ltr" className="mx-1">bash scripts/setup_codespace.sh dashboard-probe</code>
            وضعیت PostgreSQL و APIهای امضاشده را بررسی کند.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
