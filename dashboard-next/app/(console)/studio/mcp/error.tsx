"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

/** A failed read cannot certify a previous consent or revocation outcome. */
export default function McpError({ reset }: { reset: () => void }) {
  return <section role="alert" className="max-w-xl space-y-4 rounded-xl border bg-card p-6">
    <h1 className="text-lg font-semibold">وضعیت اتصال‌ها دریافت نشد</h1>
    <p className="text-sm leading-7 text-muted-foreground">نشست، دسترسی فروشگاه و ارتباط سرویس را بررسی کنید. این خطا به معنی ثبت یا لغو دسترسی قبلی نیست.</p>
    <div className="flex flex-wrap gap-3"><Button onClick={reset}>دریافت دوبارهٔ وضعیت</Button>
      <Button asChild variant="outline"><Link href="/account">حساب کاربری</Link></Button></div>
  </section>;
}
