"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
export default function RuntimeErrorPage({
  reset
}: {
  reset: () => void;
}) {
  return <div role="alert" className="max-w-xl space-y-5 rounded-xl border bg-card p-6">
  <h1 className="text-xl font-bold">وضعیت Runtime دریافت نشد</h1>
  <p className="text-sm leading-7 text-muted-foreground">اطلاعات این صفحه در دسترس نیست. ارتباط سرویس، نشست و مجوز فروشگاه را بررسی کنید. هیچ نتیجهٔ انتشار یا اجرا از این خطا قابل برداشت نیست.</p>
  <div className="flex flex-wrap gap-3">
    <Button onClick={reset}>دریافت دوبارهٔ وضعیت</Button>
    <Button asChild variant="outline">
      <Link href="/studio/workflows">فرایندها</Link>
    </Button>
  </div>
</div>;
}
