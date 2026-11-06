"use client";

import Link from "next/link";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Global route-level error boundary.
 *
 * Display no stack traces, private API responses or payment details. Next's
 * optional digest is an opaque reference an operator can use in server logs.
 */
export default function ApplicationError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-center p-5" dir="rtl">
      <Card className="w-full">
        <CardHeader className="space-y-3">
          <AlertTriangle aria-hidden="true" className="size-9 text-destructive" />
          <CardTitle className="text-xl">بارگذاری این صفحه با مشکل روبه‌رو شد</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <p role="alert" className="text-sm leading-7 text-muted-foreground">
            صفحه دریافت نشد. دوباره بارگذاری کنید.
            برای جلوگیری از عملیات تکراری، پیش از ثبت دوبارهٔ پرداخت یا بازپرداخت
            آخرین وضعیت را در پنل بررسی کنید.
          </p>
          {error.digest ? (
            <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">اطلاعات پشتیبانی</summary><p dir="ltr" className="break-all">Error reference: {error.digest}</p></details>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button type="button" onClick={reset}>
              <RefreshCw aria-hidden="true" className="size-4" />
              بارگذاری دوباره
            </Button>
            <Button asChild variant="outline">
              <Link href="/login">بازگشت به ورود</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
